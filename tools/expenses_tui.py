#!/usr/bin/env python3
"""
expenses_tui.py — gestor de gastos (TUI), Mod+G
════════════════════════════════════════════════════════════════
uso  : python3 expenses_tui.py   (o config/waybar/scripts/expenses-launch.sh)
db   : ~/.local/state/dotfiles/expenses/expenses.db  (o $EXPENSES_DB) — esquema
       y moneda principal en expenses_db.py

Cuatro páginas (1-4):
  1 Overview      resumen del mes (h/l cambia de mes), cuentas, presupuesto
                  por categoría y movimientos del mes
  2 Installments  compras en cuotas: avance, lo que falta y cada cuota
  3 Recurring     gastos/ingresos fijos; se generan solos al abrir la TUI
                  cuando llega la fecha (p los genera a mano)
  4 Cards         tarjetas: resumen cerrado, ciclo en curso, cuotas que
                  vienen y deuda; p carga el pago del resumen

Al abrirse pide las cotizaciones a internet (expenses_rates.py, en un hilo
aparte; sin red quedan las últimas) y recién después genera los fijos
vencidos, así los que son en otra moneda usan la del día.

i importa un backup de Money Manager (expenses_import.py: muestra lo nuevo y
los posibles duplicados antes de aplicar), $ cambia la fuente de cada
cotización (o la fija a mano), c exporta CSV. La gestión (cuentas,
categorías, cotizaciones, import) también está en Settings → Finances
(FinancesView, abajo). Estilo común de las TUIs: tools/dtui.py.
════════════════════════════════════════════════════════════════
"""

import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dtui import THEME as T, ConfirmModal, DApp, DView, Field, FormModal, KeyHints, Panel, PickModal, Table, bar, css  # noqa: E402
from expenses_db import (ACCT_ICONS, ACCT_TYPES, AUTO_CURRENCIES, FREQS, MAIN_CURRENCY, Database,  # noqa: E402
                       add_months)
import expenses_import as importer  # noqa: E402
import expenses_rates as rates  # noqa: E402

from rich.text import Text  # noqa: E402
from textual.app import ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.containers import Horizontal, Vertical  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.widgets import Static  # noqa: E402

db = Database()

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# (id, título, tablas de la página en orden de tab)
PAGES = [("overview", "Overview", ["txn", "acc", "cat"]),
         ("plans", "Installments", ["plan", "inst"]),
         ("rec", "Recurring", ["rec"]),
         ("cards", "Cards", ["card", "cyc"])]
# Tipos del formulario de transacción: los ajustes de saldo son ingreso/gasto con adjust=1
FORM_TYPES = [("▼ expense", "expense"), ("▲ income", "income"), ("⇄ transfer", "transfer"),
              ("± balance adjust (+)", "adj_in"), ("± balance adjust (−)", "adj_out")]


# Símbolo por moneda (sin símbolo conocido, solo el código)
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "CNY": "¥", "INR": "₹", "BRL": "R$", "ARS": "$",
           "MXN": "$", "CLP": "$", "COP": "$", "UYU": "$", "CAD": "$", "AUD": "$", "CHF": "CHF "}


def money(v: float, cur: str = "") -> str:
    """Monto con el símbolo de su moneda (o de la principal) y el código si se pasa."""
    v = 0.0 if abs(v) < 0.005 else v            # sin "-0.00" por restos de punto flotante
    sym = SYMBOLS.get(cur or MAIN_CURRENCY, "")
    return f"{'-' if v < 0 else ''}{sym}{abs(v):,.2f}" + (f" {cur}" if cur else "")


def parse_num(text: str) -> float:
    """Monto como lo escriba uno: 15999.50, 15999,50, 15.999,50, 15,999.50,
    $ 15.999 (punto de miles), -200. ValueError si no es un número."""
    t = text.strip().replace("$", "").replace(" ", "")
    if not t:
        return 0.0
    sign = -1 if t.startswith("-") else 1
    t = t.lstrip("+-")
    if "," in t and "." in t:                     # el último separador es el decimal
        dec, thou = (",", ".") if t.rfind(",") > t.rfind(".") else (".", ",")
        t = t.replace(thou, "").replace(dec, ".")
    elif "," in t:                                # 1,5 → decimal; 1,000,000 → miles
        t = t.replace(",", "") if t.count(",") > 1 else t.replace(",", ".")
    elif t.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", t):
        t = t.replace(".", "")                    # 15.999 / 1.500.000 → miles
    if not re.fullmatch(r"\d+(\.\d+)?|\.\d+", t):
        raise ValueError(text)
    return sign * float(t)


def parse_date(text: str) -> date:
    """Fecha como AAAA-MM-DD, DD/MM/AAAA, DD/MM/AA, DD/MM (este año), hoy/ayer."""
    t = text.strip().lower()
    today = date.today()
    if t in ("", "hoy", "today"):
        return today
    if t in ("ayer", "yesterday"):
        return date.fromordinal(today.toordinal() - 1)
    if m := re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2}|\d{4}))?", t):
        y = int(m[3]) if m[3] else today.year
        return date(y + 2000 if y < 100 else y, int(m[2]), int(m[1]))
    return date.fromisoformat(t)


def num_check(label: str, v: dict, key: str, positive: bool = False) -> Optional[str]:
    """Valida el monto v[key] y lo deja normalizado ("15999.5") para el guardado."""
    try:
        n = parse_num(v[key])
    except ValueError:
        return f"{label}: '{v[key]}' is not a number"
    if positive and n <= 0:
        return f"{label}: must be greater than 0"
    v[key] = repr(n) if v[key].strip() else ""
    return None


def date_check(label: str, v: dict, key: str, optional: bool = False) -> Optional[str]:
    """Valida la fecha v[key] y la deja como AAAA-MM-DD."""
    if optional and not v[key].strip():
        v[key] = ""
        return None
    try:
        v[key] = parse_date(v[key]).isoformat()
    except ValueError:
        return f"{label}: '{v[key]}' is not a date (DD/MM/YYYY or YYYY-MM-DD)"
    return None


def day_check(label: str, value: str) -> Optional[str]:
    return None if re.fullmatch(r"\d{1,2}", value or "0") and 0 <= int(value or 0) <= 31 \
        else f"{label}: a day between 1 and 31 (0 = none)"


def ddmm(d: date | str) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return d.strftime("%d/%m")


def accounts_choices(cards_only: bool = False) -> list[tuple[str, str]]:
    # Las ocultas van al final (siguen en la lista: si no, editar uno de sus movimientos la cambiaría)
    return [(f"{ACCT_ICONS.get(a['type'], '◻')} {a['name']}" + (" (hidden)" if a["hidden"] else ""), str(a["id"]))
            for a in db.q("SELECT id, name, type, hidden FROM accounts ORDER BY hidden, sort, name")
            if not cards_only or a["type"] == "card"]


def categories_choices() -> list[tuple[str, str]]:
    return [("— no category —", "0")] + [
        (f"{'▲' if c['kind'] == 'income' else '▼'} {c['icon']} {c['name']}", str(c["id"]))
        for c in db.q("SELECT id, name, icon, kind FROM categories ORDER BY kind DESC, sort, name")]


def currency_choices(blank: str) -> list[tuple[str, str]]:
    return [(blank, "")] + [(c["code"], c["code"]) for c in db.q("SELECT code FROM currencies ORDER BY code")]


class Form(FormModal):
    """FormModal que además avisa el error con una notificación: en una
    ventana chica la línea de error del pie del formulario queda tapada."""

    def action_submit(self) -> None:
        vals = self.values()
        if self.validate and (err := self.validate(vals)):
            self.query_one("#form-error").update(f"✗ {err}")
            self.app.notify_err(err)
            return
        self.dismiss(vals)


# ════════════════════════════════════════════════════════════════
#  IMPORT — revisar antes de aplicar
# ════════════════════════════════════════════════════════════════
class ImportScreen(ModalScreen[bool]):
    """Lista de lo que trae el backup: space marca/desmarca, a / u marcan o
    desmarcan todo lo visible del grupo, ctrl+s importa."""

    BINDINGS = [Binding("escape", "cancel", "cancel"), Binding("space", "toggle", show=False),
                Binding("a", "all(True)", show=False), Binding("u", "all(False)", show=False),
                Binding("ctrl+s", "apply", show=False)]
    KINDS = [("currency", "Currencies"), ("account", "Accounts"), ("category", "Categories"),
             ("budget", "Budgets"), ("recurring", "Recurring"), ("txn", "Transactions")]
    STATUS = {"new": ("new", "status_ok"), "dup": ("duplicate?", "status_warn"),
              "changed": ("changed in app", "primary")}

    def __init__(self, an: importer.Analysis) -> None:
        super().__init__()
        self.an = an
        self.by_key = {f"{it.kind}:{it.key}": it for it in an.items}

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal") as box:
            box.border_title = f" Import · {self.an.path.name} "
            box.border_subtitle = " space toggle · a/u all/none in group · ctrl+s import · esc cancel "
            yield Static(id="imp-sum")
            yield Table(id="imp")

    def on_mount(self) -> None:
        an, m = self.an, T["muted"]
        s = Text()
        for label, n, col in (("new", an.count("new"), T["status_ok"]),
                              ("possible duplicates", an.count("dup"), T["status_warn"]),
                              ("changed in the app", an.count("changed"), T["primary"]),
                              ("already imported", sum(an.same.values()), m),
                              ("ignored before", an.ignored, m)):
            s.append(f"{n} ", style=f"bold {col}")
            s.append(f"{label}    ", style=m)
        s.append("\nUnchecked items are remembered and won't be offered again (duplicates get linked to what "
                 "you already have). Accounts, categories and installment plans used by an imported item are "
                 "always created.", style=m)
        for sk in an.skipped:
            s.append(f"\nskipped: {sk}", style=m)
        self.query_one("#imp-sum", Static).update(s)
        t = self.query_one("#imp", Table)
        for label, key, w in (("", "inc", 3), ("Status", "st", 15), ("Date", "date", 10),
                              ("Description", "desc", 40), ("Account", "acc", 28), ("Amount", "amt", 20),
                              ("Detail", "det", 40)):
            t.add_column(label, key=key, width=w)
        rows = []
        for kind, title in self.KINDS:
            its = [i for i in an.items if i.kind == kind]
            if not its:
                continue
            rows.append((f"hdr:{kind}", ["", "", "", Text(f"{title} ({len(its)})", style=f"bold {T['primary']}"),
                                          "", "", ""]))
            for it in its:
                st, col = self.STATUS[it.status]
                amt = Text(money(it.amount, it.currency), style=T["status_error"] if it.amount < 0 else "") \
                    if it.amount is not None else Text("")
                rows.append((f"{it.kind}:{it.key}", [self.mark(it), Text(st, style=T[col]), Text(it.date, style=m),
                                                     it.label, it.account, amt, Text(it.detail, style=m)]))
        t.set_rows(rows)
        t.first_selectable()
        t.focus()

    def mark(self, it: importer.Item) -> Text:
        return Text("●", style=T["status_ok"]) if it.include else Text("○", style=T["muted"])

    def action_toggle(self) -> None:
        t = self.query_one("#imp", Table)
        key = t.selected_key()
        if key in self.by_key:
            it = self.by_key[key]
            it.include = not it.include
            t.update_cell(key, "inc", self.mark(it))

    def on_data_table_row_selected(self, event: Table.RowSelected) -> None:
        event.stop()
        self.action_toggle()

    def action_all(self, on: bool) -> None:
        t = self.query_one("#imp", Table)
        key = t.selected_key()
        if key not in self.by_key:
            return
        kind = self.by_key[key].kind
        for k, it in self.by_key.items():
            if it.kind == kind:
                it.include = on
                t.update_cell(k, "inc", self.mark(it))

    def action_apply(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


# ════════════════════════════════════════════════════════════════
#  GESTIÓN — lo comparten la TUI y la sección Finances de Settings
# ════════════════════════════════════════════════════════════════
class Manage:
    """Cuentas, categorías, cotizaciones, import y export. Lo usan ExpensesApp
    (una App) y FinancesView (una DView dentro de Settings): `_a` es la app en
    los dos casos. Cada una define refresh_all()."""

    @property
    def _a(self):
        return self if isinstance(self, DApp) else self.app

    def delete_account(self, key: int) -> None:
        r = db.q1("SELECT name FROM accounts WHERE id=?", (key,))
        self._confirm_delete("account", f"Delete account '{r['name']}' and ALL its transactions?",
                             "DELETE FROM accounts WHERE id=?", key)

    def delete_category(self, key: int) -> None:
        r = db.q1("SELECT name FROM categories WHERE id=?", (key,))
        self._confirm_delete("category", f"Delete category '{r['name']}'? Its transactions stay, without category.",
                             "DELETE FROM categories WHERE id=?", key)

    def _confirm_delete(self, what: str, msg: str, sql: str, key) -> None:
        def done(yes: bool) -> None:
            if yes:
                db.run(sql, (key,))
                self.refresh_all()
                self._a.notify_ok(f"{what} deleted")

        self._a.push_screen(ConfirmModal(f"Delete {what}", msg), done)

    # ── cotizaciones ──

    def update_rates(self) -> None:
        """Pide las cotizaciones en un hilo (la TUI no espera a la red) y al
        volver las guarda y genera los fijos vencidos."""
        pairs = [(c["code"], src) for c in db.q("SELECT code, source FROM currencies WHERE code<>?", (MAIN_CURRENCY,))
                 if (src := rates.effective_source(c["code"], c["source"])) != "manual"]

        def job() -> None:
            res = rates.fetch_all(pairs)
            self._a.call_from_thread(self.apply_rates, res)

        self.run_worker(job, thread=True, exclusive=True, group="rates")

    def apply_rates(self, res: dict) -> None:
        ok, bad = [], []
        for code, (rate, info) in res.items():
            if rate is None:
                bad.append(f"{code} ({info})")
            else:
                db.run("UPDATE currencies SET rate=?, updated=? WHERE code=?", (rate, info, code))
                ok.append(f"{code} {money(rate)}")
        posted = db.post_recurring()
        self.refresh_all()
        if bad:
            self._a.notify_err(f"couldn't update {', '.join(bad)}: using the last saved rate")
        if posted:
            self._a.notify_ok(f"recurring posted: {', '.join(posted[:6])}" + (" …" if len(posted) > 6 else ""))

    def rates_line(self) -> str:
        parts = []
        for c in db.q("SELECT * FROM currencies WHERE code<>? ORDER BY code", (MAIN_CURRENCY,)):
            src = rates.effective_source(c["code"], c["source"])
            parts.append(f"{c['code']} {money(c['rate'])}" if c["rate"] else f"{c['code']} ?")
            if src not in (rates.default_source(c["code"]), "manual"):
                parts[-1] += f" ({rates.source_label(src)})"
        return " · ".join(parts)

    def action_csv(self) -> None:
        path = Path.home() / f"expenses-export-{date.today().isoformat()}.csv"
        path.write_text(db.export_csv(), encoding="utf-8")
        self._a.notify_ok(f"exported → {path}")

    # ── monedas ──

    def action_currencies(self) -> None:
        rows = []
        for c in db.q("SELECT * FROM currencies ORDER BY code"):
            if c["code"] == MAIN_CURRENCY:
                rows.append((c["code"], [c["code"], Text("main currency", style=T["muted"]), "", ""]))
                continue
            src = rates.effective_source(c["code"], c["source"])
            label = rates.source_label(src)
            rows.append((c["code"], [c["code"], money(c["rate"], MAIN_CURRENCY) if c["rate"] else "?",
                                     Text(label, style=T["muted"]), Text(c["updated"], style=T["muted"])]))
        rows.append(("+new", [Text("+ add currency", style=T["primary"]), "", "", ""]))

        def picked(code: Optional[str]) -> None:
            if not code or code == MAIN_CURRENCY:
                return
            r = db.q1("SELECT * FROM currencies WHERE code=?", (code,))
            src = rates.effective_source(r["code"], r["source"]) if r else "manual"

            def check(v: dict) -> Optional[str]:
                if not v["code"]:
                    return "The code is missing"
                if not r and db.q1("SELECT 1 FROM currencies WHERE code=?", (v["code"].upper(),)):
                    return f"{v['code'].upper()} already exists"
                return num_check("Rate", v, "rate", positive=v["src"] == "manual")

            def done(v: Optional[dict]) -> None:
                if not v:
                    return
                c = v["code"].upper()
                rate = float(v["rate"] or 0)
                db.run("INSERT INTO currencies(code, rate, source, updated) VALUES(?,?,?,?) ON CONFLICT(code) DO "
                       "UPDATE SET source=excluded.source" + (", rate=excluded.rate, updated=excluded.updated"
                                                             if v["src"] == "manual" else ""),
                       (c, rate, v["src"], "manual" if v["src"] == "manual" else ""))
                self.refresh_all()
                if v["src"] == "manual":
                    self._a.notify_ok(f"{c} = {money(rate, MAIN_CURRENCY)} (manual)")
                else:
                    self.update_rates()
                    self._a.notify_ok(f"{c}: updating…")

            self._a.push_screen(Form("Exchange rate", [
                Field("code", "Code", r["code"] if r else "", placeholder="USD, EUR, BRL…"),
                Field("src", "Source", src, choices=rates.source_choices(r["code"] if r else "")),
                Field("rate", f"Rate: 1 unit = how many {MAIN_CURRENCY} (manual only)",
                      f"{r['rate']:g}" if r and r["rate"] else ""),
            ], hint="Online rates are refreshed every time the TUI opens (and with r).", validate=check), done)

        self._a.push_screen(PickModal("Exchange rates", ["Currency", "Rate", "Source", "Updated"], rows), picked)

    # ── import ──

    def action_import_mm(self) -> None:
        dl = Path.home() / "Downloads"
        default = dl / "money_android.sqlite"
        start = str(default if default.exists() else dl) + ("" if default.exists() else "/")

        def chosen(v: Optional[dict]) -> None:
            if not v:
                return
            path = Path(v["path"]).expanduser()
            try:
                an = importer.analyze(path, db)
            except Exception as e:  # noqa: BLE001 - archivo que no es un backup de Money Manager
                return self._a.notify_err(f"can't read {path.name}: {e}")
            if not an.items:
                return self._a.notify_ok(f"nothing new · {sum(an.same.values())} already imported"
                                      + (f" · {an.ignored} ignored" if an.ignored else ""))
            self._a.push_screen(ImportScreen(an), lambda go: self.run_import(an) if go else None)

        self._a.push_screen(Form("Import from Money Manager", [
            Field("path", "Backup file (.sqlite exported from the app)", start, files=True),
        ], hint="Nothing is written until you review the list and press ctrl+s.",
            validate=lambda v: None if Path(v["path"]).expanduser().is_file() else "File not found"), chosen)

    def run_import(self, an: importer.Analysis) -> None:
        try:
            st = importer.apply(an, db)
        except Exception as e:  # noqa: BLE001
            return self._a.notify_err(f"import failed, nothing changed: {e}")
        posted = db.post_recurring()
        self.refresh_all()
        parts = [f"{st[k]} {k}" for k in ("transactions", "updated", "accounts", "categories", "recurring",
                                          "budgets", "currencies") if st.get(k)]
        self._a.notify_ok("imported: " + (", ".join(parts) or "nothing") + (f" · {len(posted)} recurring posted"
                                                                          if posted else ""))

    # ── cuentas y categorías ──

    def acc_form(self, key: Optional[int] = None, preset: Optional[dict] = None) -> None:
        r = db.q1("SELECT * FROM accounts WHERE id=?", (key,)) if key else None
        p = preset or {}
        pay = [("—", "")] + [c for c in accounts_choices() if c[1] != str(key)]
        # Al editar se muestra el saldo de HOY: cambiarlo guarda la diferencia como ajuste
        # (el saldo inicial queda como está; tocarlo sumaría a todos los movimientos)
        now = round(db.balances().get(key, 0.0), 2) if key else 0.0

        def check(v: dict) -> Optional[str]:
            return ("The name is missing" if not v["name"] else num_check("Balance", v, "bal")
                    or day_check("Closing day", v["close"]) or day_check("Due day", v["due"]))

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            card = v["type"] == "card"
            bal = float(v["bal"] or 0)
            args = (v["name"], v["type"], v["cur"], v["notes"],
                    int(v["close"] or 0) if card else 0, int(v["due"] or 0) if card else 0,
                    int(v["pay"]) if card and v["pay"] else None, int(v["hidden"]))
            try:
                if key:
                    db.run("UPDATE accounts SET name=?,type=?,currency=?,notes=?,close_day=?,pay_day=?,"
                           "pay_account_id=?,hidden=? WHERE id=?", (*args, key))
                else:
                    db.run("INSERT INTO accounts(name,type,currency,notes,close_day,pay_day,pay_account_id,"
                           "hidden,init_bal) VALUES(?,?,?,?,?,?,?,?,?)", (*args, bal))
            except Exception as e:  # noqa: BLE001 - ej. nombre repetido
                return self._a.notify_err(f"error: {e}")
            adj = db.set_balance(key, bal) if key else None
            self.refresh_all()
            self._a.notify_ok(f"account '{v['name']}' saved" + (f" · balance adjusted to {money(bal)}" if adj else ""))

        self._a.push_screen(Form("Edit account" if r else "New account", [
            Field("name", "Name", r["name"] if r else "", placeholder="e.g. Bank, Visa, Wallet, Cash…"),
            Field("type", "Type", r["type"] if r else p.get("type", "bank"),
                  choices=[(f"{i} {lbl}", k) for k, lbl, i in ACCT_TYPES]),
            Field("cur", "Currency", r["currency"] if r else MAIN_CURRENCY, choices=currency_choices("—")[1:]),
            Field("bal", ("Balance today (a change is saved as a balance adjustment"
                          + ("; cards: negative = what you owe)" if r["type"] == "card" else ")")) if r
                  else "Initial balance", f"{now:.2f}" if r else "0"),
            Field("close", "Credit card: closing day (0 = none)", str(r["close_day"]) if r else "0"),
            Field("due", "Credit card: due day", str(r["pay_day"]) if r else "0"),
            Field("pay", "Credit card: paid from", str(r["pay_account_id"] or "") if r else "", choices=pay),
            Field("hidden", "Hidden", str(r["hidden"]) if r else "0", choices=[("no", "0"), ("yes", "1")]),
            Field("notes", "Notes (optional)", r["notes"] if r else ""),
        ], validate=check), done)

    def cat_form(self, key: Optional[int] = None) -> None:
        r = db.q1("SELECT * FROM categories WHERE id=?", (key,)) if key else None

        def check(v: dict) -> Optional[str]:
            return "The name is missing" if not v["name"] else num_check("Budget", v, "budget")

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            args = (v["name"], v["kind"], v["icon"] or "◻", float(v["budget"] or 0))
            try:
                if key:
                    db.run("UPDATE categories SET name=?,kind=?,icon=?,budget=? WHERE id=?", (*args, key))
                else:
                    db.run("INSERT INTO categories(name,kind,icon,budget) VALUES(?,?,?,?)", args)
            except Exception as e:  # noqa: BLE001
                return self._a.notify_err(f"error: {e}")
            self.refresh_all()
            self._a.notify_ok(f"category '{v['name']}' saved")

        self._a.push_screen(Form("Edit category" if r else "New category", [
            Field("name", "Name", r["name"] if r else "", placeholder="e.g. Groceries"),
            Field("kind", "Kind", r["kind"] if r else "expense",
                  choices=[("▼ expense", "expense"), ("▲ income", "income")]),
            Field("icon", "Icon (emoji or symbol)", r["icon"] if r else "◻"),
            Field("budget", "Monthly budget (0 = no limit; b sets a single month)",
                  f"{r['budget']:g}" if r else "0"),
        ], validate=check), done)


# ════════════════════════════════════════════════════════════════
#  APP
# ════════════════════════════════════════════════════════════════
class ExpensesApp(Manage, DApp):
    TITLE = "Expenses"
    CSS = DApp.CSS + css("""
    #tabs { height: 1; padding: 0 2; }
    .page { height: 1fr; }
    #summary { height: 3; }
    #middle { height: 2fr; }
    #acc-panel, #cat-panel { width: 1fr; }
    #txn-panel { height: 3fr; }
    #plan-panel { height: 3fr; }
    #inst-panel { height: 2fr; }
    #card-panel { height: 2fr; }
    #cyc-panel { height: 3fr; }
    ImportScreen .modal { width: 96%%; height: 92%%; max-height: 92%%; }
    ImportScreen #imp { height: 1fr; }
    ImportScreen #imp-sum { height: auto; margin-bottom: 1; }
    """)

    BINDINGS = [
        Binding("1", "page(0)", show=False, description="page: overview"),
        Binding("2", "page(1)", show=False, description="page: installments"),
        Binding("3", "page(2)", show=False, description="page: recurring"),
        Binding("4", "page(3)", show=False, description="page: cards"),
        Binding("tab", "cycle(1)", show=False, description="next page"),
        Binding("shift+tab", "cycle(-1)", show=False, description="previous page"),
        Binding("n", "new", "new"),
        Binding("t", "new_txn", "transaction"),
        Binding("e", "edit", "edit"),
        Binding("x", "delete", "delete"),
        Binding("h", "month(-1)", "previous month"),
        Binding("l", "month(1)", "next month"),
        Binding("b", "budget", "month budget"),
        Binding("p", "pay", "pay card / post recurring"),
        Binding("s", "statement", "set card statement"),
        Binding("space", "toggle", "pause recurring"),
        Binding("i", "import_mm", "import Money Manager"),
        Binding("dollar_sign", "currencies", "exchange rates"),
        Binding("c", "csv", "export csv"),
        Binding("r", "refresh", "refresh"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.page = 0
        self.month = date.today().replace(day=1)

    def compose(self) -> ComposeResult:
        yield Static(id="tabs")
        with Vertical(id="page-overview", classes="page"):
            yield Panel(Static(id="stats"), title="Summary", id="summary")
            with Horizontal(id="middle"):
                yield Panel(Table(id="acc"), title="Accounts", id="acc-panel")
                yield Panel(Table(id="cat"), title="Budget", id="cat-panel")
            yield Panel(Table(id="txn"), title="Transactions", id="txn-panel")
        with Vertical(id="page-plans", classes="page"):
            yield Panel(Table(id="plan"), title="Installment plans", id="plan-panel")
            yield Panel(Table(id="inst"), title="Installments", id="inst-panel")
        with Vertical(id="page-rec", classes="page"):
            yield Panel(Table(id="rec"), title="Recurring", id="rec-panel")
        with Vertical(id="page-cards", classes="page"):
            yield Panel(Table(id="card"), title="Credit cards", id="card-panel")
            yield Panel(Table(id="cyc"), title="Current cycle", id="cyc-panel")
        yield KeyHints(id="hints")

    def on_mount(self) -> None:
        cols = {
            "acc": [("Account", 24), ("Balance", 20), ("Txns", 5)],
            "cat": [("Category", 22), ("Spent", 14), ("Budget", 22)],
            "txn": [("Date", 6), ("Description", 40), ("Type", 10), ("Account", 26), ("Category", 20),
                    ("Amount", 18)],
            "plan": [("Description", 36), ("Card", 12), ("Paid", 16), ("Each", 14), ("Remaining", 16),
                     ("Next", 6), ("Ends", 8)],
            "inst": [("#", 7), ("Date", 10), ("Amount", 16), ("Status", 10)],
            "rec": [("", 2), ("Description", 30), ("Type", 10), ("Account", 22), ("Category", 20),
                    ("Amount", 20), ("Every", 8), ("Next", 10)],
            "card": [("Card", 16), ("Closes", 7), ("Due", 7), ("Closed statement", 34), ("Current cycle", 16),
                     ("Upcoming inst.", 16), ("Debt", 16)],
            "cyc": [("Date", 6), ("Description", 40), ("Category", 20), ("Amount", 18)],
        }
        for tid, cs in cols.items():
            t = self.query_one(f"#{tid}", Table)
            for label, w in cs:
                t.add_column(label, width=w)
        self.show_page(0)
        self.update_rates()

    # ── páginas ──

    def show_page(self, i: int) -> None:
        self.page = i
        for n, (pid, _, _) in enumerate(PAGES):
            self.query_one(f"#page-{pid}").display = n == i
        tabs = Text()
        for n, (_, title, _) in enumerate(PAGES):
            on = n == i
            tabs.append(f" {n + 1} ", style=f"bold {T['background']} on {T['primary']}" if on else T["muted"])
            tabs.append(f" {title}   ", style=f"bold {T['primary']}" if on else T["muted"])
        self.query_one("#tabs", Static).update(tabs)
        self.refresh_all()
        self.query_one(f"#{PAGES[i][2][0]}", Table).focus()

    def action_page(self, i: int) -> None:
        self.show_page(i)

    def refresh_all(self) -> None:
        [self.refresh_overview, self.refresh_plans, self.refresh_rec, self.refresh_cards][self.page]()
        self.update_hints()

    # ── 1 overview ──

    def refresh_overview(self) -> None:
        ok, err, muted = T["status_ok"], T["status_error"], T["muted"]
        ym, today = self.month.strftime("%Y-%m"), date.today().isoformat()
        bal = db.balances()
        accs = db.q("SELECT * FROM accounts ORDER BY hidden, sort, name")
        nw = sum(db.convert(bal.get(a["id"], 0), a["currency"], MAIN_CURRENCY) or 0 for a in accs
                 if not a["hidden"])
        out = db.val("SELECT SUM(amount) FROM transactions WHERE type='expense' AND adjust=0 AND date LIKE ?",
                     (ym + "%",))
        inc = db.val("SELECT SUM(amount) FROM transactions WHERE type='income' AND adjust=0 AND date LIKE ?",
                     (ym + "%",))
        s = Text()
        for label, value, style in (("net worth", money(nw, MAIN_CURRENCY), "bold"),
                                    ("expenses", f"-{money(out)}", f"bold {err}"),
                                    ("income", f"+{money(inc)}", f"bold {ok}"),
                                    ("balance", ("+" if inc >= out else "-") + money(abs(inc - out)),
                                     f"bold {ok if inc >= out else err}")):
            s.append(f"{label} ", style=muted)
            s.append(value, style=style)
            s.append("    ")
        self.query_one("#stats", Static).update(s)
        summary = self.query_one("#summary")
        summary.border_title = f" Summary · {MONTHS[self.month.month - 1]} {self.month.year} "
        summary.border_subtitle = f" {self.rates_line()} · h/l month "

        # cuentas, agrupadas por tipo
        counts = {r[0]: r[1] for r in db.q("SELECT account_id, count(*) FROM transactions GROUP BY 1")}
        rows, last = [], None
        labels = {k: lbl for k, lbl, _ in ACCT_TYPES}
        for a in sorted(accs, key=lambda a: (a["hidden"], [k for k, _, _ in ACCT_TYPES].index(a["type"])
                                             if a["type"] in labels else 99, a["sort"], a["name"])):
            group = "hidden" if a["hidden"] else labels.get(a["type"], a["type"])
            if group != last:
                rows.append((f"hdr:{group}", [Text(group, style=f"bold {muted}"), "", ""]))
                last = group
            b = bal.get(a["id"], 0)
            rows.append((str(a["id"]), [Text(f"{ACCT_ICONS.get(a['type'], '◻')} {a['name']}",
                                             style=muted if a["hidden"] else ""),
                                        Text(money(b, a["currency"]), style=ok if b > -0.005 else f"bold {err}"),
                                        Text(str(counts.get(a["id"], 0)), style=muted)]))
        self.query_one("#acc", Table).set_rows(rows)
        self.query_one("#acc-panel").border_subtitle = "" if accs else " n new · i import "

        # presupuesto por categoría
        spent = {r[0]: r[1] for r in db.q("""SELECT category_id, SUM(amount) FROM transactions
                                             WHERE adjust=0 AND type IN ('expense','income') AND date LIKE ?
                                             GROUP BY 1""", (ym + "%",))}
        rows = []
        for kind, title in (("expense", "expenses"), ("income", "income")):
            cats = db.q("SELECT * FROM categories WHERE kind=? ORDER BY sort, name", (kind,))
            if not cats:
                continue
            rows.append((f"hdr:{kind}", [Text(title, style=f"bold {muted}"), "", ""]))
            for c in cats:
                sp = spent.get(c["id"], 0)
                if kind == "income":
                    b = Text("")
                elif (bud := db.budget_for(c["id"], ym)) > 0:
                    pct = sp / bud * 100
                    col = err if pct >= 100 else T["status_warn"] if pct >= 80 else ok
                    b = bar(pct, 8)
                    b.stylize(col, 0, min(8, int(round(pct * 8 / 100))))
                    b.append(f" {pct:3.0f}% of {bud / 1000:,.0f}k", style=col)
                else:
                    b = Text("no limit", style=muted)
                rows.append((str(c["id"]), [f"{c['icon']} {c['name']}",
                                            Text(money(sp), style="" if sp else muted), b]))
        self.query_one("#cat", Table).set_rows(rows)
        self.query_one("#cat-panel").border_title = f" Budget · {MONTHS[self.month.month - 1]} "

        # movimientos del mes
        rows = [self.txn_row(r, today) for r in db.q(self.TXN_SQL + " WHERE tx.date LIKE ? "
                                                     "ORDER BY tx.date DESC, tx.time DESC, tx.id DESC", (ym + "%",))]
        self.query_one("#txn", Table).set_rows(rows)
        fut = sum(1 for r in db.q("SELECT 1 FROM transactions WHERE date LIKE ? AND date > ?", (ym + "%", today)))
        self.query_one("#txn-panel").border_subtitle = (
            f" {len(rows)} transactions" + (f" · {fut} scheduled ◷" if fut else "") + " " if rows
            else " t new transaction · h/l month ")

    TXN_SQL = """
        SELECT tx.*, a.name AS aname, a.currency, c.name AS cname, c.icon AS cicon,
               ta.name AS taname, p.n AS pn
        FROM transactions tx
        JOIN accounts a ON a.id = tx.account_id
        LEFT JOIN categories c ON c.id = tx.category_id
        LEFT JOIN accounts ta ON ta.id = tx.to_account_id
        LEFT JOIN plans p ON p.id = tx.plan_id"""

    def txn_row(self, r, today: str, short: bool = False) -> tuple[str, list]:
        err, ok, muted = T["status_error"], T["status_ok"], T["muted"]
        kind, sign, col = {"expense": ("▼ expense", "-", err), "income": ("▲ income", "+", ok)}.get(
            r["type"], ("⇄ transfer", "", T["primary"]))
        future = r["date"] > today
        desc = Text(("◷ " if future else "") + r["description"], style=muted if future else "")
        if r["plan_id"]:
            desc.append(f" ({r['inst_no']}/{r['pn']})", style=muted)
        if r["orig_currency"]:
            desc.append(f" · {r['orig_amount']:,.2f} {r['orig_currency']}", style=muted)
        if r["fee_of"]:
            desc.append(" · fee", style=muted)
        if r["adjust"]:
            cat = Text("± adjust", style=muted)
        else:
            cat = Text(f"{r['cicon']} {r['cname']}") if r["cname"] else Text("—", style=muted)
        amt = Text(f"{sign}{money(r['amount'], r['currency'])}", style=muted if future else col)
        d = Text(ddmm(r["date"]), style=muted)
        if short:
            return str(r["id"]), [d, desc, cat, amt]
        acc = r["aname"] + (f" → {r['taname']}" if r["taname"] else "")
        return str(r["id"]), [d, desc, Text(kind, style=col), acc, cat, amt]

    # ── 2 cuotas ──

    def refresh_plans(self) -> None:
        today, muted = date.today().isoformat(), T["muted"]
        nm = add_months(date.today(), 1, 1).strftime("%Y-%m")
        active, done = [], []
        pending_total = next_month = 0.0
        for p in db.q("""
                SELECT p.*, a.name AS aname,
                       SUM(CASE WHEN t.date <= ? THEN 1 ELSE 0 END) AS paid, COUNT(t.id) AS cnt,
                       SUM(CASE WHEN t.date > ? THEN t.amount ELSE 0 END) AS remaining,
                       SUM(CASE WHEN t.date LIKE ? THEN t.amount ELSE 0 END) AS nextm,
                       MIN(CASE WHEN t.date > ? THEN t.date END) AS nxt, MAX(t.date) AS last,
                       (SELECT amount FROM transactions WHERE plan_id=p.id ORDER BY inst_no DESC LIMIT 1) AS each_
                FROM plans p JOIN accounts a ON a.id = p.account_id
                LEFT JOIN transactions t ON t.plan_id = p.id
                GROUP BY p.id ORDER BY last, p.description""", (today, today, nm + "%", today)):
            paid = (p["paid"] or 0) + (p["n"] - (p["cnt"] or 0))     # cuotas que faltan en la base = ya pagas
            pct = paid / p["n"] * 100 if p["n"] else 100
            prog = bar(pct, 8)
            prog.append(f" {paid}/{p['n']}", style=muted)
            rem = p["remaining"] or 0
            pending_total += rem
            next_month += p["nextm"] or 0
            row = (str(p["id"]), [p["description"], p["aname"], prog, money(p["each_"] or 0),
                                  Text(money(rem), style=T["status_error"] if rem else muted),
                                  Text(ddmm(p["nxt"]) if p["nxt"] else "—", style=muted),
                                  Text(date.fromisoformat(p["last"]).strftime("%m/%y") if p["last"] else "—",
                                       style=muted)])
            (active if rem else done).append(row)
        rows = active + ([("hdr:done", [Text("finished", style=f"bold {muted}"), "", "", "", "", "", ""])] + done
                         if done else [])
        t = self.query_one("#plan", Table)
        t.set_rows(rows)
        t.first_selectable(t.cursor_row or 0)
        self.query_one("#plan-panel").border_subtitle = (
            f" pending {money(pending_total)} · next month {money(next_month)} " if rows
            else " n new purchase in installments ")
        self.refresh_inst()

    def refresh_inst(self) -> None:
        key = self.query_one("#plan", Table).selected_key()
        rows = []
        panel = self.query_one("#inst-panel")
        if key and not key.startswith("hdr:"):
            p = db.q1("SELECT * FROM plans WHERE id=?", (int(key),))
            today = date.today().isoformat()
            for r in db.q("SELECT * FROM transactions WHERE plan_id=? ORDER BY inst_no, date", (int(key),)):
                paid = r["date"] <= today
                rows.append((str(r["id"]), [f"{r['inst_no']}/{p['n']}", Text(r["date"], style=T["muted"]),
                                            money(r["amount"]),
                                            Text("✓ paid" if paid else "◷ pending",
                                                 style=T["status_ok"] if paid else T["muted"])]))
            panel.border_title = f" Installments · {p['description']} "
            panel.border_subtitle = f" total {money(p['total'])} in {p['n']} "
        else:
            panel.border_title, panel.border_subtitle = " Installments ", ""
        self.query_one("#inst", Table).set_rows(rows)

    # ── 3 fijos ──

    def refresh_rec(self) -> None:
        ok, err, muted = T["status_ok"], T["status_error"], T["muted"]
        rows = []
        tot = {"expense": 0.0, "income": 0.0}
        for r in db.q("""SELECT r.*, a.name AS aname, a.currency AS acur, ta.name AS taname,
                                c.name AS cname, c.icon AS cicon
                         FROM recurring r JOIN accounts a ON a.id = r.account_id
                         LEFT JOIN accounts ta ON ta.id = r.to_account_id
                         LEFT JOIN categories c ON c.id = r.category_id
                         ORDER BY r.active DESC, r.next_date, r.description"""):
            kind, sign, col = {"expense": ("▼ expense", "-", err), "income": ("▲ income", "+", ok)}.get(
                r["type"], ("⇄ transfer", "", T["primary"]))
            cur = r["currency"] or r["acur"]
            if r["active"] and r["freq"] == "monthly" and r["type"] in tot:
                tot[r["type"]] += db.convert(r["amount"], cur, MAIN_CURRENCY) or 0
            rows.append((str(r["id"]), [
                Text("●", style=ok) if r["active"] else Text("○", style=muted),
                Text(r["description"], style="" if r["active"] else muted), Text(kind, style=col),
                r["aname"] + (f" → {r['taname']}" if r["taname"] else ""),
                f"{r['cicon']} {r['cname']}" if r["cname"] else Text("—", style=muted),
                Text(f"{sign}{money(r['amount'], cur)}", style=col if r["active"] else muted),
                Text(r["freq"], style=muted),
                Text(r["next_date"] if r["active"] else "paused", style=muted)]))
        self.query_one("#rec", Table).set_rows(rows)
        self.query_one("#rec-panel").border_subtitle = (
            f" monthly: out {money(tot['expense'])} · in {money(tot['income'])} " if rows
            else " n new recurring expense or income ")

    # ── 4 tarjetas ──

    def card_info(self, a, today: date) -> Optional[dict]:
        return db.card_status(a, today)

    def refresh_cards(self) -> None:
        ok, err, muted = T["status_ok"], T["status_error"], T["muted"]
        today, bal = date.today(), db.balances()
        rows = []
        for a in db.q("SELECT * FROM accounts WHERE type='card' ORDER BY hidden, sort, name"):
            ci = self.card_info(a, today)
            debt = -bal.get(a["id"], 0)
            if ci:
                left = ci["closed"] - ci["paid"]
                st = Text(money(ci["closed"]))
                st.append("  ✓ paid" if left <= 0.5 else f"  {money(left)} left",
                          style=ok if left <= 0.5 else T["status_warn"])
                cells = [Text(ddmm(ci["next_close"]), style=muted), Text(ddmm(ci["next_due"]), style=muted), st,
                         money(ci["current"]), Text(money(ci["upcoming"]), style=muted)]
            else:
                cells = [Text("—", style=muted)] * 5
            rows.append((str(a["id"]), [Text(a["name"], style=muted if a["hidden"] else ""), *cells,
                                        Text(money(debt), style=f"bold {err}" if debt > 0.005 else ok)]))
        t = self.query_one("#card", Table)
        t.set_rows(rows)
        self.query_one("#card-panel").border_subtitle = (" s set statement · p pay · e closing / due day " if rows
                                                         else " no credit cards (account type: credit card) ")
        self.refresh_cycle()

    def refresh_cycle(self) -> None:
        key = self.query_one("#card", Table).selected_key()
        panel, rows = self.query_one("#cyc-panel"), []
        a = db.q1("SELECT * FROM accounts WHERE id=?", (int(key),)) if key else None
        if a and (ci := self.card_info(a, date.today())):
            today = date.today().isoformat()
            rows = [self.txn_row(r, today, short=True) for r in db.q(
                self.TXN_SQL + " WHERE tx.account_id=? AND tx.type<>'transfer' AND tx.date > ? AND tx.date <= ? "
                               "ORDER BY tx.date DESC, tx.time DESC", (a["id"], ci["last_close"].isoformat(),
                                                                       ci["next_close"].isoformat()))]
            panel.border_title = (f" Current cycle · {a['name']} · {ddmm(ci['last_close'])} → "
                                  f"{ddmm(ci['next_close'])} ")
            panel.border_subtitle = f" {money(ci['current'])} · due {ddmm(ci['next_due'])} "
        else:
            panel.border_title, panel.border_subtitle = " Current cycle ", ""
        self.query_one("#cyc", Table).set_rows(rows)

    def on_data_table_row_highlighted(self, event: Table.RowHighlighted) -> None:
        if event.data_table.id == "plan":
            self.refresh_inst()
        elif event.data_table.id == "card":
            self.refresh_cycle()

    # ── foco y atajos ──

    def focused_table(self) -> str:
        tables = PAGES[self.page][2]
        f = self.focused
        return f.id if isinstance(f, Table) and f.id in tables else tables[0]

    def update_hints(self) -> None:
        tid = self.focused_table()
        h = {
            "txn": [("t", "new"), ("e", "edit"), ("x", "delete"), ("h/l", "month")],
            "acc": [("n", "new account"), ("e", "edit"), ("x", "delete"), ("$", "rates")],
            "cat": [("n", "new category"), ("e", "edit"), ("b", "month budget"), ("x", "delete")],
            "plan": [("n", "new purchase"), ("e", "edit"), ("x", "delete plan")],
            "inst": [("e", "edit installment")],
            "rec": [("n", "new"), ("e", "edit"), ("x", "delete"), ("space", "pause"), ("p", "post due")],
            "card": [("s", "set statement"), ("p", "pay"), ("e", "edit card"), ("t", "new transaction")],
            "cyc": [("e", "edit"), ("x", "delete")],
        }[tid]
        self.set_hints(h + [("tab", "panel"), ("1-4", "page"), ("i", "import"), ("q", "quit")])

    def on_descendant_focus(self, _event) -> None:
        self.update_hints()

    def sel(self, tid: str) -> Optional[int]:
        key = self.query_one(f"#{tid}", Table).selected_key()
        return int(key) if key and key[0].isdigit() else None

    def action_cycle(self, step: int) -> None:
        tables = PAGES[self.page][2]
        i = tables.index(self.focused_table())
        self.query_one(f"#{tables[(i + step) % len(tables)]}", Table).focus()

    def action_month(self, step: int) -> None:
        if self.page == 0:
            self.month = add_months(self.month, step, 1)
            self.refresh_all()

    def action_refresh(self) -> None:
        self.refresh_all()
        self.update_rates()
        self.notify_ok("data refreshed · updating exchange rates")

    def on_data_table_row_selected(self, event: Table.RowSelected) -> None:
        if event.data_table.id in PAGES[self.page][2]:
            self.action_edit()

    def action_new(self) -> None:
        tid = self.focused_table()
        {"txn": self.txn_form, "acc": self.acc_form, "cat": self.cat_form, "rec": self.rec_form,
         "plan": lambda: self.txn_form(preset={"inst": "3"}), "inst": lambda: self.txn_form(preset={"inst": "3"}),
         "card": lambda: self.acc_form(preset={"type": "card"}), "cyc": self.txn_form}[tid]()

    def action_new_txn(self) -> None:
        preset = {}
        if self.focused_table() in ("card", "cyc") and (k := self.sel("card")):
            preset["acc"] = str(k)
        self.txn_form(preset=preset)

    def action_edit(self) -> None:
        tid = self.focused_table()
        if (key := self.sel(tid)) is None:
            return
        {"txn": self.txn_form, "inst": self.txn_form, "cyc": self.txn_form, "acc": self.acc_form,
         "card": self.acc_form, "cat": self.cat_form, "plan": self.plan_form, "rec": self.rec_form}[tid](key)

    def action_delete(self) -> None:
        tid = self.focused_table()
        if (key := self.sel(tid)) is None:
            return
        if tid in ("txn", "inst", "cyc"):
            r = db.q1("SELECT description, amount, plan_id FROM transactions WHERE id=?", (key,))
            msg = f"Delete '{r['description']}' ({money(r['amount'])})?"
            if r["plan_id"]:
                msg += "\nOnly this installment: to delete the whole purchase use the Installments page."
            sql, what = "DELETE FROM transactions WHERE id=?", "transaction"
        elif tid in ("acc", "card"):
            return self.delete_account(key)
        elif tid == "cat":
            return self.delete_category(key)
        elif tid == "plan":
            r = db.q1("SELECT description, n FROM plans WHERE id=?", (key,))
            msg, sql, what = (f"Delete '{r['description']}' and its {r['n']} installments?",
                              "DELETE FROM plans WHERE id=?", "purchase")
        else:
            r = db.q1("SELECT description FROM recurring WHERE id=?", (key,))
            msg, sql, what = (f"Delete recurring '{r['description']}'? Already posted transactions stay.",
                              "DELETE FROM recurring WHERE id=?", "recurring")

        self._confirm_delete(what, msg, sql, key)

    def action_toggle(self) -> None:
        if self.focused_table() == "rec" and (key := self.sel("rec")) is not None:
            db.run("UPDATE recurring SET active = 1 - active WHERE id=?", (key,))
            self.refresh_all()

    def action_pay(self) -> None:
        tid = self.focused_table()
        if tid == "rec":
            posted = db.post_recurring()
            self.refresh_all()
            self.notify_ok(f"posted: {', '.join(posted)}" if posted else "nothing due")
            return
        if tid not in ("card", "cyc") or (key := self.sel("card")) is None:
            return
        a = db.q1("SELECT * FROM accounts WHERE id=?", (key,))
        ci = self.card_info(a, date.today())
        amount = max(0.0, ci["closed"] - ci["paid"]) if ci else max(0.0, -db.balances().get(key, 0))
        self.txn_form(preset={
            "type": "transfer", "to": str(key), "acc": str(a["pay_account_id"] or ""),
            "amount": f"{amount:.2f}", "date": date.today().isoformat(),
            "desc": f"Card payment {a['name']} " + (MONTHS[ci["last_close"].month - 1] if ci else "")})

    def action_statement(self) -> None:
        """Cargar el resumen como lo muestra el banco: las diferencias con lo
        registrado quedan como ajustes (el cerrado con fecha del cierre, el
        ciclo en curso con fecha de hoy), así cuadran resumen, ciclo y deuda."""
        if self.focused_table() not in ("card", "cyc") or (key := self.sel("card")) is None:
            return
        a = db.q1("SELECT * FROM accounts WHERE id=?", (key,))
        ci = self.card_info(a, date.today())
        if not ci:
            return self.notify_err(f"{a['name']} has no closing day: set it with e")

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            n = 0
            if v["closed"] and db.adjust(key, ci["closed"] - float(v["closed"]), ci["last_close"].isoformat(),
                                         "Statement adjustment", v["note"]):
                n += 1
            if v["current"] and db.adjust(key, ci["current"] - float(v["current"]), None,
                                          "Cycle adjustment", v["note"]):
                n += 1
            self.refresh_all()
            self.notify_ok(f"{a['name']}: {n} adjustment(s) saved" if n else "nothing to adjust")

        self.push_screen(Form(f"Statement · {a['name']}", [
            Field("closed", f"Closed statement ({ddmm(ci['prev_close'])} → {ddmm(ci['last_close'])}), total billed",
                  f"{ci['closed']:.2f}"),
            Field("current", f"Current cycle so far ({ddmm(ci['last_close'])} → {ddmm(ci['next_close'])})",
                  f"{ci['current']:.2f}"),
            Field("note", "Note (optional)", ""),
        ], hint=f"Paid since the closing: {money(ci['paid'])} (payments are transfers: p). "
                "Differences with what's recorded are saved as adjustments.",
            validate=lambda v: num_check("Closed statement", v, "closed") or num_check("Current cycle", v, "current")),
            done)

    def action_budget(self) -> None:
        if self.focused_table() != "cat" or (key := self.sel("cat")) is None:
            return
        c = db.q1("SELECT * FROM categories WHERE id=?", (key,))
        ym = self.month.strftime("%Y-%m")
        cur = db.q1("SELECT amount FROM budgets WHERE category_id=? AND month=?", (key, ym))

        def done(v: Optional[dict]) -> None:
            if v is None:
                return
            if v["amount"]:
                db.run("INSERT OR REPLACE INTO budgets(category_id, month, amount) VALUES(?,?,?)",
                       (key, ym, float(v["amount"])))
            else:
                db.run("DELETE FROM budgets WHERE category_id=? AND month=?", (key, ym))
            self.refresh_all()
            self.notify_ok(f"budget of {c['name']} for {ym} saved")

        self.push_screen(Form(f"Budget · {c['name']} · {MONTHS[self.month.month - 1]} {self.month.year}", [
            Field("amount", f"Amount for this month (empty = default {money(c['budget'])})",
                  f"{cur['amount']:g}" if cur else ""),
        ], validate=lambda v: num_check("Amount", v, "amount")), done)

    # ── formularios ──

    def txn_form(self, key: Optional[int] = None, preset: Optional[dict] = None) -> None:
        accts = accounts_choices()
        if not accts:
            self.notify_err("Create an account first (Overview → Accounts → n) or import (i)")
            return
        r = db.q1("SELECT * FROM transactions WHERE id=?", (key,)) if key else None
        p = preset or {}
        if r:
            ftype = ("adj_in" if r["type"] == "income" else "adj_out") if r["adjust"] else r["type"]
            vals = {"desc": r["description"], "date": r["date"], "type": ftype, "acc": str(r["account_id"]),
                    "to": str(r["to_account_id"] or "0"), "cat": str(r["category_id"] or "0"), "note": r["note"],
                    "amount": f"{r['orig_amount'] if r['orig_currency'] else r['amount']:g}",
                    "cur": r["orig_currency"]}
        else:
            vals = {"desc": "", "date": date.today().isoformat(), "type": "expense", "acc": accts[0][1],
                    "to": "0", "cat": "0", "note": "", "amount": "", "cur": "", "inst": "1"} | p
        acc_cur = {str(a["id"]): a["currency"] for a in db.q("SELECT id, currency FROM accounts")}

        def check(v: dict) -> Optional[str]:
            if not v["desc"]:
                return "The description is missing"
            if err := num_check("Amount", v, "amount", positive=True) or date_check("The date", v, "date"):
                return err
            if v["type"] == "transfer" and v["to"] in ("0", v["acc"]):
                return "Pick a different destination account for the transfer"
            if v["cur"] and db.convert(1, v["cur"], acc_cur[v["acc"]]) is None:
                return f"No exchange rate for {v['cur']} (press $ on the main screen)"
            if "inst" in v and (not v["inst"].isdigit() or not 1 <= int(v["inst"]) <= 120):
                return "Installments: a number from 1 to 120"
            if "inst" in v and int(v["inst"]) > 1 and v["type"] != "expense":
                return "Installments only apply to expenses"
            return None

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            acc = int(v["acc"])
            typ, adjust = {"adj_in": ("income", 1), "adj_out": ("expense", 1)}.get(v["type"], (v["type"], 0))
            entered = float(v["amount"])
            cur = v["cur"] if v["cur"] and v["cur"] != acc_cur[v["acc"]] else ""
            amount = db.convert(entered, cur, acc_cur[v["acc"]]) if cur else entered
            to = int(v["to"]) if typ == "transfer" and v["to"] != "0" else None
            to_amount = (db.convert(amount, acc_cur[v["acc"]], acc_cur[v["to"]])
                         if to and acc_cur[v["to"]] != acc_cur[v["acc"]] else None)
            cat = None if adjust else (int(v["cat"]) or None)
            f = dict(type=typ, account_id=acc, to_account_id=to, category_id=cat, amount=amount,
                     description=v["desc"], note=v["note"], date=v["date"], adjust=adjust,
                     orig_amount=entered if cur else None, orig_currency=cur, to_amount=to_amount)
            if key:
                sets = ", ".join(f"{k}=?" for k in f)
                db.run(f"UPDATE transactions SET {sets} WHERE id=?", (*f.values(), key))
                self.notify_ok(f"{v['desc']} — {money(amount)}")
            elif int(v.get("inst") or 1) > 1:
                n = int(v["inst"])
                db.create_plan(v["desc"], acc, cat, amount, n, date.fromisoformat(v["date"]), v["note"])
                self.notify_ok(f"{v['desc']} — {n} × {money(round(amount / n, 2))}")
            else:
                db.add_txn(**f)
                db.con.commit()
                self.notify_ok(f"{v['desc']} — {money(amount)}")
            self.refresh_all()

        fields = [
            Field("desc", "Description", vals["desc"], placeholder="e.g. groceries, salary, card payment…"),
            Field("amount", "Amount (total, for installments too)", vals["amount"], placeholder="0.00"),
            Field("cur", "Paid in", vals["cur"], choices=currency_choices("account's currency")),
            Field("date", "Date (DD/MM/YYYY; for installments, the first one)", vals["date"]),
            Field("type", "Type", vals["type"], choices=FORM_TYPES),
            Field("acc", "Account", vals["acc"], choices=accts),
            Field("to", "Destination account (transfers only)", vals["to"], choices=[("—", "0")] + accts),
            Field("cat", "Category", vals["cat"], choices=categories_choices()),
        ]
        if not r:
            fields.append(Field("inst", "Installments (1 = single payment)", vals["inst"]))
        fields.append(Field("note", "Note (optional)", vals["note"]))
        title = "Edit transaction" if r else ("New purchase in installments" if p.get("inst", "1") != "1"
                                              else "New transaction")
        if r and r["plan_id"]:
            title += f" · installment {r['inst_no']}"
        self.push_screen(Form(title, fields, validate=check), done)

    def plan_form(self, key: int) -> None:
        r = db.q1("SELECT * FROM plans WHERE id=?", (key,))

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            cat = int(v["cat"]) or None
            db.run("UPDATE plans SET description=?, category_id=? WHERE id=?", (v["desc"], cat, key))
            db.run("UPDATE transactions SET description=?, category_id=? WHERE plan_id=?", (v["desc"], cat, key))
            self.refresh_all()
            self.notify_ok(f"'{v['desc']}' saved (all installments)")

        self.push_screen(Form("Edit purchase in installments", [
            Field("desc", "Description", r["description"]),
            Field("cat", "Category", str(r["category_id"] or "0"), choices=categories_choices()),
        ], hint="Applies to every installment. To change one amount, edit it in the list below.",
            validate=lambda v: None if v["desc"] else "The description is missing"), done)

    def rec_form(self, key: Optional[int] = None) -> None:
        accts = accounts_choices()
        if not accts:
            self.notify_err("Create an account first")
            return
        r = db.q1("SELECT * FROM recurring WHERE id=?", (key,)) if key else None

        def check(v: dict) -> Optional[str]:
            if not v["desc"]:
                return "The description is missing"
            if v["type"] == "transfer" and v["to"] in ("0", v["acc"]):
                return "Pick a different destination account for the transfer"
            return (num_check("Amount", v, "amount", positive=True) or date_check("Next date", v, "next")
                    or date_check("End date", v, "end", optional=True))

        def done(v: Optional[dict]) -> None:
            if not v:
                return
            nxt = date.fromisoformat(v["next"])
            args = (v["desc"], v["type"], int(v["acc"]), int(v["to"]) if v["type"] == "transfer" else None,
                    int(v["cat"]) or None, float(v["amount"]), v["cur"], v["freq"], nxt.day, v["next"], v["end"],
                    int(v["active"]))
            if key:
                db.run("UPDATE recurring SET description=?,type=?,account_id=?,to_account_id=?,category_id=?,amount=?,"
                       "currency=?,freq=?,day=?,next_date=?,end_date=?,active=? WHERE id=?", (*args, key))
            else:
                db.run("INSERT INTO recurring(description,type,account_id,to_account_id,category_id,amount,currency,"
                       "freq,day,next_date,end_date,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", args)
            posted = db.post_recurring()
            self.refresh_all()
            self.notify_ok(f"recurring '{v['desc']}' saved" + (f" · {len(posted)} posted" if posted else ""))

        self.push_screen(Form("Edit recurring" if r else "New recurring", [
            Field("desc", "Description", r["description"] if r else "", placeholder="e.g. Netflix, rent, salary"),
            Field("amount", "Amount", f"{r['amount']:g}" if r else ""),
            Field("cur", "Currency", r["currency"] if r else "", choices=currency_choices("account's currency")),
            Field("type", "Type", r["type"] if r else "expense", choices=FORM_TYPES[:3]),
            Field("acc", "Account", str(r["account_id"]) if r else accts[0][1], choices=accts),
            Field("to", "Destination account (transfers only)", str(r["to_account_id"] or "0") if r else "0",
                  choices=[("—", "0")] + accts),
            Field("cat", "Category", str(r["category_id"] or "0") if r else "0", choices=categories_choices()),
            Field("freq", "Every", r["freq"] if r else "monthly", choices=[(f, f) for f in FREQS]),
            Field("next", "Next date (DD/MM/YYYY)", r["next_date"] if r else date.today().isoformat()),
            Field("end", "End date (optional)", r["end_date"] if r else ""),
            Field("active", "Active", str(r["active"]) if r else "1", choices=[("yes", "1"), ("paused", "0")]),
        ], hint="It's posted as a transaction when the date arrives (on opening the TUI).", validate=check), done)


# ════════════════════════════════════════════════════════════════
#  SETTINGS → FINANCES
# ════════════════════════════════════════════════════════════════
LAUNCHER = Path.home() / ".config" / "waybar" / "scripts" / "expenses-launch.sh"


class FinancesView(Manage, DView):
    """Sección Finances de Settings: cuentas, categorías, cotizaciones,
    import de Money Manager y export. Los movimientos, cuotas, fijos y
    tarjetas siguen en la TUI (o la abre, Mod+G)."""

    FOCUS = "#facc"
    TABLES = ["facc", "fcat", "fcur"]
    BINDINGS = [
        Binding("tab", "cycle(1)", show=False, description="next panel"),
        Binding("shift+tab", "cycle(-1)", show=False, description="previous panel"),
        Binding("n", "new", "new"),
        Binding("e", "edit", "edit"),
        Binding("x", "delete", "delete"),
        Binding("i", "import_mm", "import Money Manager"),
        Binding("c", "csv", "export csv"),
        Binding("u", "rates", "update exchange rates"),
        Binding("o", "open_tui", "open the expenses TUI"),
    ]
    DEFAULT_CSS = css("""
    FinancesView #fin-top { height: 1fr; }
    FinancesView #facc-panel { width: 3fr; }
    FinancesView #fcat-panel { width: 2fr; }
    FinancesView #fcur-panel { height: 9; }
    """)

    def compose(self) -> ComposeResult:
        with Horizontal(id="fin-top"):
            yield Panel(Table(id="facc"), title="Accounts", id="facc-panel")
            yield Panel(Table(id="fcat"), title="Categories", id="fcat-panel")
        yield Panel(Table(id="fcur"), title="Exchange rates", id="fcur-panel")

    def on_mount(self) -> None:
        for tid, cols in (("facc", [("Account", 26), ("Type", 16), ("Balance", 20), ("Card", 18)]),
                          ("fcat", [("Category", 24), ("Kind", 10), ("Monthly budget", 16)]),
                          ("fcur", [("Currency", 10), ("Rate", 18), ("Source", 26), ("Updated", 18)])):
            t = self.query_one(f"#{tid}", Table)
            for label, w in cols:
                t.add_column(label, width=w)
        self.refresh_all()

    def refresh_all(self) -> None:
        muted, ok, err = T["muted"], T["status_ok"], T["status_error"]
        bal, labels = db.balances(), {k: lbl for k, lbl, _ in ACCT_TYPES}
        rows = []
        for a in db.q("SELECT * FROM accounts ORDER BY hidden, sort, name"):
            b = bal.get(a["id"], 0.0)
            rows.append((str(a["id"]), [
                Text(f"{ACCT_ICONS.get(a['type'], '◻')} {a['name']}", style=muted if a["hidden"] else ""),
                Text(labels.get(a["type"], a["type"]) + (" · hidden" if a["hidden"] else ""), style=muted),
                Text(money(b, a["currency"]), style=ok if b > -0.005 else err),
                Text(f"closes {a['close_day']} · due {a['pay_day']}" if a["close_day"] else "", style=muted)]))
        self.query_one("#facc", Table).set_rows(rows)
        self.query_one("#facc-panel").border_subtitle = f" {len(rows)} accounts " if rows else " n new · i import "
        rows = []
        for kind, title in (("expense", "expenses"), ("income", "income")):
            cats = db.q("SELECT * FROM categories WHERE kind=? ORDER BY sort, name", (kind,))
            if cats:
                rows.append((f"hdr:{kind}", [Text(title, style=f"bold {muted}"), "", ""]))
            rows += [(str(c["id"]), [f"{c['icon']} {c['name']}", Text(kind, style=muted),
                                     money(c["budget"]) if c["budget"] else Text("no limit", style=muted)])
                     for c in cats]
        t = self.query_one("#fcat", Table)
        t.set_rows(rows)
        rows = []
        for c in db.q("SELECT * FROM currencies ORDER BY code"):
            src = rates.effective_source(c["code"], c["source"])
            main = c["code"] == MAIN_CURRENCY
            rows.append((c["code"], [c["code"], Text("main currency", style=muted) if main
                                     else money(c["rate"], MAIN_CURRENCY) if c["rate"] else Text("?", style=err),
                                     Text("" if main else rates.source_label(src), style=muted),
                                     Text(c["updated"], style=muted)]))
        self.query_one("#fcur", Table).set_rows(rows)
        self.query_one("#fcur-panel").border_subtitle = " u update online rates · e change source "
        self.update_hints()

    def focused_table(self) -> str:
        f = self.app.focused
        return f.id if isinstance(f, Table) and f.id in self.TABLES else "facc"

    def hints(self) -> list[tuple[str, str]]:
        what = {"facc": "account", "fcat": "category", "fcur": "currency"}[self.focused_table()]
        return [("n", f"new {what}"), ("e", "edit"), ("x", "delete"), ("tab", "panel"), ("i", "import"),
                ("u", "rates"), ("c", "csv"), ("o", "open expenses")]

    def sel(self) -> Optional[str]:
        key = self.query_one(f"#{self.focused_table()}", Table).selected_key()
        return None if not key or key.startswith(("hdr:", "gap:")) else key

    def action_cycle(self, step: int) -> None:
        i = self.TABLES.index(self.focused_table())
        self.query_one(f"#{self.TABLES[(i + step) % len(self.TABLES)]}", Table).focus()

    def action_new(self) -> None:
        {"facc": self.acc_form, "fcat": self.cat_form, "fcur": self.action_currencies}[self.focused_table()]()

    def action_edit(self) -> None:
        tid, key = self.focused_table(), self.sel()
        if tid == "fcur":
            self.action_currencies()
        elif key:
            (self.acc_form if tid == "facc" else self.cat_form)(int(key))

    def on_data_table_row_selected(self, event: Table.RowSelected) -> None:
        if event.data_table.id in self.TABLES:
            event.stop()
            self.action_edit()

    def action_delete(self) -> None:
        tid, key = self.focused_table(), self.sel()
        if not key:
            return
        if tid == "facc":
            self.delete_account(int(key))
        elif tid == "fcat":
            self.delete_category(int(key))
        elif key in (MAIN_CURRENCY, *AUTO_CURRENCIES):
            self._a.notify_err(f"{key} can't be deleted (set it to manual instead)")
        else:
            self._confirm_delete("currency", f"Delete {key}?", "DELETE FROM currencies WHERE code=?", key)

    def action_rates(self) -> None:
        self.update_rates()
        self._a.notify_ok("updating exchange rates…")

    def action_open_tui(self) -> None:
        cmd = ["bash", str(LAUNCHER)] if LAUNCHER.exists() else [sys.executable, str(Path(__file__).resolve())]
        subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ExpensesApp().run()
