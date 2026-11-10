"""Expenses (GUI): paridad con la TUI tools/expenses_tui.py.

Pestañas Overview (mes, cuentas, presupuesto, movimientos), Installments (compras en
cuotas y cada cuota), Recurring (fijos), Cards (resumen, ciclo, pago) y Manage
(cuentas, categorías, cotizaciones, import de Money Manager y export CSV).
Reusa la lógica de la TUI (validaciones, formularios, base) importando expenses_tui.py; la
base es la misma que usa la TUI (expenses_db.py). Al abrir pide las
cotizaciones en un hilo y después genera los fijos vencidos, igual que la TUI.
Finances (Settings) usa manage_groups()/act() de acá.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import date
from pathlib import Path

from . import _lib as L

sys.path.insert(0, str(L.TOOLS))

UI: dict = {}
LOCK = threading.RLock()
STATE = {"month": date.today().replace(day=1), "plan": None, "card": None, "import": None,
         "rates": "", "rates_started": False}
TABS = [("overview", "Overview"), ("plans", "Installments"), ("rec", "Recurring"), ("cards", "Cards"),
        ("manage", "Manage")]
_G = None


def G():
    """La TUI como biblioteca (money, parse_num, checks, choices, db)."""
    global _G
    if _G is None:
        import expenses_tui as g  # tools/expenses_tui.py
        _G = g
    return _G


def db():
    return G().db


def money(v, cur: str = "") -> str:
    return G().money(v or 0.0, cur)


def pairs(choices) -> list:
    return [[lbl, val] for lbl, val in choices]


def fld(name: str, label: str, vals: dict, choices=None, placeholder: str = "") -> dict:
    f = {"name": name, "label": label.upper(), "text": str(vals.get(name, "") if vals.get(name) is not None else "")}
    if choices is not None:
        f["choices"] = pairs(choices)
    return f


def search_ok(*texts) -> bool:
    q = (UI.get("search") or "").strip().lower()
    return not q or any(q in (t or "").lower() for t in texts)


# ════════════════════════════════════════════════════════════════
#  cotizaciones (como la TUI al abrir: hilo, después fijos vencidos)
# ════════════════════════════════════════════════════════════════

def update_rates(wait: bool = False) -> str:
    g, rates = G(), __import__("expenses_rates")
    with LOCK:
        pairs_ = [(c["code"], src) for c in db().q("SELECT code, source FROM currencies WHERE code<>?", (g.MAIN_CURRENCY,))
                  if (src := rates.effective_source(c["code"], c["source"])) != "manual"]

    def job() -> str:
        res = rates.fetch_all(pairs_)
        with LOCK:
            bad = []
            for code, (rate, info) in res.items():
                if rate is None:
                    bad.append(f"{code} ({info})")
                else:
                    db().run("UPDATE currencies SET rate=?, updated=? WHERE code=?", (rate, info, code))
            posted = db().post_recurring()
        msg = []
        if bad:
            msg.append(f"Couldn't update {', '.join(bad)}: using the last saved rate")
        if posted:
            msg.append(f"Recurring posted: {', '.join(posted[:6])}" + (" …" if len(posted) > 6 else ""))
        STATE["rates"] = " · ".join(msg)
        return STATE["rates"] or "Exchange rates updated"

    if wait:
        return job()
    threading.Thread(target=job, daemon=True).start()
    return ""


def rates_line() -> str:
    g, rates = G(), __import__("expenses_rates")
    parts = []
    for c in db().q("SELECT * FROM currencies WHERE code<>? ORDER BY code", (g.MAIN_CURRENCY,)):
        src = rates.effective_source(c["code"], c["source"])
        parts.append(f"{c['code']} {money(c['rate'])}" if c["rate"] else f"{c['code']} ?")
        if src not in (rates.default_source(c["code"]), "manual"):
            parts[-1] += f" ({rates.source_label(src)})"
    return " · ".join(parts)


# ════════════════════════════════════════════════════════════════
#  filas
# ════════════════════════════════════════════════════════════════

TXN_SQL = """
    SELECT tx.*, a.name AS aname, a.currency, c.name AS cname, c.icon AS cicon,
           ta.name AS taname, p.n AS pn
    FROM transactions tx
    JOIN accounts a ON a.id = tx.account_id
    LEFT JOIN categories c ON c.id = tx.category_id
    LEFT JOIN accounts ta ON ta.id = tx.to_account_id
    LEFT JOIN plans p ON p.id = tx.plan_id"""

KIND = {"expense": ("▼ expense", "-", "#e06c75"), "income": ("▲ income", "+", "#98c379")}


def txn_item(r, today: str, short: bool = False):
    kind, sign, _ = KIND.get(r["type"], ("⇄ transfer", "", ""))
    future = r["date"] > today
    desc = ("◷ " if future else "") + (r["description"] or "(no description)")
    if r["plan_id"]:
        desc += f" ({r['inst_no']}/{r['pn']})"
    extra = []
    if r["orig_currency"]:
        extra.append(f"{r['orig_amount']:,.2f} {r['orig_currency']}")
    if r["fee_of"]:
        extra.append("fee")
    cat = "± adjust" if r["adjust"] else (f"{r['cicon']} {r['cname']}" if r["cname"] else "no category")
    sub = [G().ddmm(r["date"])]
    if not short:
        sub += [kind, r["aname"] + (f" → {r['taname']}" if r["taname"] else "")]
    sub += [cat] + extra
    return L.item(f"txn:edit:{r['id']}", desc, sub=" · ".join(sub), right=f"{sign}{money(r['amount'], r['currency'])}",
                  glyph="󰁅" if r["type"] == "expense" else "󰁝" if r["type"] == "income" else "󰁔", on=not future,
                  actions=[L.action(f"txn:edit:{r['id']}", "Edit"), L.action(f"txn:del:{r['id']}", "Delete", True)])


def bar(pct: float, n: int = 10) -> str:
    k = max(0, min(n, int(round(pct * n / 100))))
    return "▓" * k + "░" * (n - k)


# ════════════════════════════════════════════════════════════════
#  páginas
# ════════════════════════════════════════════════════════════════

def page_overview() -> list:
    g = G()
    d = db()
    m = STATE["month"]
    ym, today = m.strftime("%Y-%m"), date.today().isoformat()
    bal = d.balances()
    accs = d.q("SELECT * FROM accounts ORDER BY hidden, sort, name")
    nw = sum(d.convert(bal.get(a["id"], 0), a["currency"], g.MAIN_CURRENCY) or 0 for a in accs if not a["hidden"])
    out = d.val("SELECT SUM(amount) FROM transactions WHERE type='expense' AND adjust=0 AND date LIKE ?", (ym + "%",))
    inc = d.val("SELECT SUM(amount) FROM transactions WHERE type='income' AND adjust=0 AND date LIKE ?", (ym + "%",))
    mname = f"{g.MONTHS[m.month - 1].capitalize()} {m.year}"
    summ = [
        L.item("month:0", mname, sub="Month shown", glyph="󰃭",
               actions=[L.action("month:-1", "‹ Previous"), L.action("month:0", "This month"), L.action("month:1", "Next ›")]),
        L.info("nw", "Net worth", money(nw, g.MAIN_CURRENCY)),
        L.info("out", "Expenses", f"-{money(out)}"),
        L.info("inc", "Income", f"+{money(inc)}"),
        L.info("bal", "Balance", ("+" if inc >= out else "-") + money(abs(inc - out))),
    ]
    if rl := rates_line():
        summ.append(L.info("rates", "Exchange rates", rl))
    groups = [L.group(f"Summary · {mname}", summ),
              L.group("Add", [L.button("txn:new", "New transaction", "Expense, income, transfer or balance adjustment", "New"),
                              L.button("txn:new:inst", "New purchase in installments", "Splits the total into monthly installments", "New")])]

    # cuentas por tipo
    counts = {r[0]: r[1] for r in d.q("SELECT account_id, count(*) FROM transactions GROUP BY 1")}
    labels = {k: lbl for k, lbl, _ in g.ACCT_TYPES}
    order = [k for k, _, _ in g.ACCT_TYPES]
    by: dict[str, list] = {}
    for a in sorted(accs, key=lambda a: (a["hidden"], order.index(a["type"]) if a["type"] in order else 99, a["sort"], a["name"])):
        grp = "Hidden" if a["hidden"] else labels.get(a["type"], a["type"])
        b = bal.get(a["id"], 0)
        by.setdefault(grp, []).append(L.item(
            f"acc:edit:{a['id']}", f"{g.ACCT_ICONS.get(a['type'], '◻')} {a['name']}",
            sub=f"{counts.get(a['id'], 0)} transactions" + ("" if b > -0.005 else " · negative"),
            right=money(b, a["currency"]), on=b > -0.005,
            actions=[L.action(f"acc:edit:{a['id']}", "Edit"), L.action(f"acc:del:{a['id']}", "Delete", True)]))
    if not accs:
        groups.append(L.group("Accounts", [L.button("acc:new", "No accounts yet", "Create one or import from Money Manager (Manage)", "New account")]))
    for grp, rows in by.items():
        groups.append(L.group(f"Accounts · {grp}", rows))

    # presupuesto
    spent = {r[0]: r[1] for r in d.q("""SELECT category_id, SUM(amount) FROM transactions
                                         WHERE adjust=0 AND type IN ('expense','income') AND date LIKE ?
                                         GROUP BY 1""", (ym + "%",))}
    for kind, title in (("expense", f"Budget · {g.MONTHS[m.month - 1]}"), ("income", "Income by category")):
        rows = []
        for c in d.q("SELECT * FROM categories WHERE kind=? ORDER BY sort, name", (kind,)):
            sp = spent.get(c["id"], 0)
            acts = [L.action(f"cat:edit:{c['id']}", "Edit")]
            if kind == "expense":
                acts.append(L.action(f"cat:budget:{c['id']}", "Month budget"))
                bud = d.budget_for(c["id"], ym)
                if bud > 0:
                    pct = sp / bud * 100
                    sub = f"{bar(pct)} {pct:3.0f}% of {money(bud)}" + ("  · over budget" if pct >= 100 else "")
                    on = pct < 100
                else:
                    sub, on = "no limit", True
            else:
                sub, on = "", True
            acts.append(L.action(f"cat:del:{c['id']}", "Delete", True))
            rows.append(L.item(f"cat:edit:{c['id']}", f"{c['icon']} {c['name']}", sub=sub, right=money(sp) if sp else "—",
                               on=on, actions=acts))
        groups.append(L.group(title, rows))

    # movimientos del mes
    rows = [txn_item(r, today) for r in d.q(TXN_SQL + " WHERE tx.date LIKE ? ORDER BY tx.date DESC, tx.time DESC, tx.id DESC",
                                            (ym + "%",))
            if search_ok(r["description"], r["aname"], r["cname"], r["note"])]
    fut = d.val("SELECT count(*) FROM transactions WHERE date LIKE ? AND date > ?", (ym + "%", today))
    groups.append(L.group(f"Transactions · {len(rows)}" + (f" · {fut} scheduled ◷" if fut else ""), rows
                          or [L.info("none", "No transactions this month", "")]))
    return groups


def page_plans() -> list:
    d = db()
    g = G()
    today = date.today().isoformat()
    nm = g.add_months(date.today(), 1, 1).strftime("%Y-%m")
    active, done = [], []
    pending_total = next_month = 0.0
    open_rows = []
    for p in d.q("""
            SELECT p.*, a.name AS aname,
                   SUM(CASE WHEN t.date <= ? THEN 1 ELSE 0 END) AS paid, COUNT(t.id) AS cnt,
                   SUM(CASE WHEN t.date > ? THEN t.amount ELSE 0 END) AS remaining,
                   SUM(CASE WHEN t.date LIKE ? THEN t.amount ELSE 0 END) AS nextm,
                   MIN(CASE WHEN t.date > ? THEN t.date END) AS nxt, MAX(t.date) AS last,
                   (SELECT amount FROM transactions WHERE plan_id=p.id ORDER BY inst_no DESC LIMIT 1) AS each_
            FROM plans p JOIN accounts a ON a.id = p.account_id
            LEFT JOIN transactions t ON t.plan_id = p.id
            GROUP BY p.id ORDER BY last, p.description""", (today, today, nm + "%", today)):
        paid = (p["paid"] or 0) + (p["n"] - (p["cnt"] or 0))
        pct = paid / p["n"] * 100 if p["n"] else 100
        rem = p["remaining"] or 0
        pending_total += rem
        next_month += p["nextm"] or 0
        if not search_ok(p["description"], p["aname"]):
            continue
        is_open = STATE["plan"] == p["id"]
        sub = (f"{p['aname']} · {bar(pct, 8)} {paid}/{p['n']} · {money(p['each_'] or 0)} each"
               + (f" · next {g.ddmm(p['nxt'])}" if p["nxt"] else "")
               + (f" · ends {date.fromisoformat(p['last']).strftime('%m/%y')}" if p["last"] else ""))
        row = L.item(f"plan:open:{p['id']}", ("▾ " if is_open else "▸ ") + p["description"], sub=sub,
                     right=f"{money(rem)} left" if rem else "✓ done", on=bool(rem),
                     actions=[L.action(f"plan:open:{p['id']}", "Hide" if is_open else "Installments"),
                              L.action(f"plan:edit:{p['id']}", "Edit"), L.action(f"plan:del:{p['id']}", "Delete", True)])
        (active if rem else done).append(row)
        if is_open:
            for r in d.q("SELECT * FROM transactions WHERE plan_id=? ORDER BY inst_no, date", (p["id"],)):
                ok_ = r["date"] <= today
                open_rows.append(L.item(f"txn:edit:{r['id']}", f"{r['inst_no']}/{p['n']}",
                                        sub=f"{r['date']} · {'✓ paid' if ok_ else '◷ pending'}", right=money(r["amount"]), on=ok_,
                                        actions=[L.action(f"txn:edit:{r['id']}", "Edit"),
                                                 L.action(f"txn:del:{r['id']}", "Delete", True)]))
            open_title = f"Installments · {p['description']} · total {money(p['total'])} in {p['n']}"
    groups = [L.group("Installments", [
        L.info("pend", "Pending", money(pending_total)), L.info("next", "Next month", money(next_month)),
        L.button("txn:new:inst", "New purchase in installments", "", "New")])]
    groups.append(L.group("Active", active))
    if open_rows:
        groups.append(L.group(open_title, open_rows))
    groups.append(L.group("Finished", done))
    return groups


def page_rec() -> list:
    g = G()
    d = db()
    rows = []
    tot = {"expense": 0.0, "income": 0.0}
    for r in d.q("""SELECT r.*, a.name AS aname, a.currency AS acur, ta.name AS taname, c.name AS cname, c.icon AS cicon
                    FROM recurring r JOIN accounts a ON a.id = r.account_id
                    LEFT JOIN accounts ta ON ta.id = r.to_account_id
                    LEFT JOIN categories c ON c.id = r.category_id
                    ORDER BY r.active DESC, r.next_date, r.description"""):
        kind, sign, _ = KIND.get(r["type"], ("⇄ transfer", "", ""))
        cur = r["currency"] or r["acur"]
        if r["active"] and r["freq"] == "monthly" and r["type"] in tot:
            tot[r["type"]] += d.convert(r["amount"], cur, g.MAIN_CURRENCY) or 0
        if not search_ok(r["description"], r["aname"], r["cname"]):
            continue
        sub = " · ".join([kind, r["aname"] + (f" → {r['taname']}" if r["taname"] else ""),
                          f"{r['cicon']} {r['cname']}" if r["cname"] else "no category", r["freq"],
                          f"next {r['next_date']}" if r["active"] else "paused"])
        rows.append(L.item(f"rec:edit:{r['id']}", r["description"], sub=sub, right=f"{sign}{money(r['amount'], cur)}",
                           on=bool(r["active"]),
                           actions=[L.action(f"rec:edit:{r['id']}", "Edit"),
                                    L.action(f"rec:toggle:{r['id']}", "Pause" if r["active"] else "Resume"),
                                    L.action(f"rec:del:{r['id']}", "Delete", True)]))
    return [L.group("Recurring", [L.info("out", "Monthly out", money(tot["expense"])),
                                  L.info("in", "Monthly in", money(tot["income"])),
                                  L.button("rec:new", "New recurring", "Fixed expense, income or transfer", "New"),
                                  L.button("rec:post", "Post due now", "Creates the transactions whose date arrived", "Post")]),
            L.group("Items", rows or [L.info("none", "No recurring items", "")])]


def page_cards() -> list:
    g = G()
    d = db()
    today, bal = date.today(), d.balances()
    rows, cyc, cyc_title = [], [], ""
    for a in d.q("SELECT * FROM accounts WHERE type='card' ORDER BY hidden, sort, name"):
        ci = d.card_status(a, today)
        debt = -bal.get(a["id"], 0)
        if ci:
            left = ci["closed"] - ci["paid"]
            sub = (f"closes {g.ddmm(ci['next_close'])} · due {g.ddmm(ci['next_due'])} · statement {money(ci['closed'])} "
                   + ("✓ paid" if left <= 0.5 else f"({money(left)} left)")
                   + f" · cycle {money(ci['current'])} · upcoming {money(ci['upcoming'])}")
        else:
            sub = "no closing day: Edit to set it"
        is_open = STATE["card"] == a["id"]
        rows.append(L.item(f"card:open:{a['id']}", ("▾ " if is_open else "▸ ") + a["name"] + (" (hidden)" if a["hidden"] else ""),
                           sub=sub, right=f"owes {money(debt)}" if debt > 0.005 else money(-debt), on=debt <= 0.005,
                           actions=[L.action(f"card:statement:{a['id']}", "Statement"), L.action(f"card:pay:{a['id']}", "Pay"),
                                    L.action(f"txn:new:acc:{a['id']}", "Transaction"), L.action(f"acc:edit:{a['id']}", "Edit")]))
        if is_open and ci:
            t = today.isoformat()
            cyc = [txn_item(r, t, short=True) for r in d.q(
                TXN_SQL + " WHERE tx.account_id=? AND tx.type<>'transfer' AND tx.date > ? AND tx.date <= ? "
                          "ORDER BY tx.date DESC, tx.time DESC", (a["id"], ci["last_close"].isoformat(), ci["next_close"].isoformat()))]
            cyc_title = (f"Current cycle · {a['name']} · {g.ddmm(ci['last_close'])} → {g.ddmm(ci['next_close'])} · "
                         f"{money(ci['current'])} · due {g.ddmm(ci['next_due'])}")
    groups = [L.group("Credit cards", rows or [L.info("none", "No credit cards", "Account type: credit card")]),
              L.group("Add", [L.button("acc:new:card", "New credit card", "", "New")])]
    if cyc_title:
        groups.insert(1, L.group(cyc_title, cyc or [L.info("none", "Nothing in this cycle", "")]))
    return groups


def manage_groups() -> list:
    g, rates = G(), __import__("expenses_rates")
    d = db()
    groups = import_groups()
    bal = d.balances()
    accs = [L.item(f"acc:edit:{a['id']}", f"{g.ACCT_ICONS.get(a['type'], '◻')} {a['name']}",
                   sub=f"{dict((k, l) for k, l, _ in g.ACCT_TYPES).get(a['type'], a['type'])} · {a['currency']}"
                   + (" · hidden" if a["hidden"] else ""), right=money(bal.get(a["id"], 0), a["currency"]), on=not a["hidden"],
                   actions=[L.action(f"acc:edit:{a['id']}", "Edit"), L.action(f"acc:del:{a['id']}", "Delete", True)])
            for a in d.q("SELECT * FROM accounts ORDER BY hidden, sort, name")]
    groups.append(L.group("Accounts", accs + [L.button("acc:new", "New account", "", "New")]))
    cats = [L.item(f"cat:edit:{c['id']}", f"{c['icon']} {c['name']}",
                   sub=("▲ income" if c["kind"] == "income" else "▼ expense") + (f" · budget {money(c['budget'])}" if c["budget"] else ""),
                   actions=[L.action(f"cat:edit:{c['id']}", "Edit")]
                   + ([L.action(f"cat:budget:{c['id']}", "Month budget")] if c["kind"] == "expense" else [])
                   + [L.action(f"cat:del:{c['id']}", "Delete", True)])
            for c in d.q("SELECT * FROM categories ORDER BY kind DESC, sort, name")]
    groups.append(L.group("Categories", cats + [L.button("cat:new", "New category", "", "New")]))
    curs = []
    for c in d.q("SELECT * FROM currencies ORDER BY code"):
        if c["code"] == g.MAIN_CURRENCY:
            curs.append(L.item(f"cur:main", c["code"], sub="main currency", glyph="󰄔"))
            continue
        src = rates.effective_source(c["code"], c["source"])
        label = rates.source_label(src)
        curs.append(L.item(f"cur:edit:{c['code']}", c["code"], sub=f"{label} · updated {c['updated'] or '—'}",
                           right=money(c["rate"], g.MAIN_CURRENCY) if c["rate"] else "?", glyph="󰄔",
                           actions=[L.action(f"cur:edit:{c['code']}", "Edit"), L.action(f"cur:del:{c['code']}", "Delete", True)]))
    groups.append(L.group("Exchange rates", curs + [
        L.button("cur:new", "Add currency", "", "Add"),
        L.button("rates", "Update exchange rates", STATE["rates"] or "DolarAPI; then posts due recurring items", "Update")]))
    groups.append(L.group("Data", [
        L.button("import", "Import from Money Manager", "Review what's new before applying", "Import"),
        L.button("csv", "Export CSV", f"~/expenses-export-{date.today().isoformat()}.csv", "Export")]))
    return groups


# ── import de Money Manager: revisión antes de aplicar ──

IMPORT_KINDS = [("currency", "Currencies"), ("account", "Accounts"), ("category", "Categories"),
                ("budget", "Budgets"), ("recurring", "Recurring"), ("txn", "Transactions")]
IMPORT_STATUS = {"new": "new", "dup": "duplicate?", "changed": "changed in app"}


def import_groups() -> list:
    an = STATE["import"]
    if not an:
        return []
    head = [L.info("sum", f"Import · {an.path.name}",
                   f"{an.count('new')} new · {an.count('dup')} possible duplicates · {an.count('changed')} changed · "
                   f"{sum(an.same.values())} already imported" + (f" · {an.ignored} ignored before" if an.ignored else "")),
            L.info("note", "Unchecked items", "remembered and not offered again; duplicates get linked"),
            L.button("imp:apply", "Apply import", "Writes the checked items", "Import"),
            L.button("imp:cancel", "Cancel import", "Nothing is written", "Cancel", danger=True)]
    head += [L.info(f"skip{i}", "Skipped", s) for i, s in enumerate(an.skipped)]
    groups = [L.group("Import review", head)]
    for kind, title in IMPORT_KINDS:
        its = [(i, it) for i, it in enumerate(an.items) if it.kind == kind]
        if not its:
            continue
        rows = [L.item(f"imp:toggle:{i}", it.label or "—",
                       sub=" · ".join(x for x in (IMPORT_STATUS.get(it.status, it.status), it.date, it.account, it.detail) if x),
                       right=money(it.amount, it.currency) if it.amount is not None else "", on=it.include,
                       glyph="󰄲" if it.include else "󰄱") for i, it in its]
        groups.append(L.group(f"Import · {title} ({len(its)})", [
            L.item(f"imp:all:{kind}", f"All {title.lower()}", sub="Check or uncheck the whole group", glyph="󰒆",
                   actions=[L.action(f"imp:all:{kind}", "Check all"), L.action(f"imp:none:{kind}", "Uncheck all")])] + rows))
    return groups


def get() -> dict:
    with LOCK:
        if not STATE["rates_started"]:
            STATE["rates_started"] = True
            update_rates()
        tab = UI.get("tab") or "overview"
        if STATE["import"]:
            tab = UI["tab"] = "manage"
        try:
            groups = {"overview": page_overview, "plans": page_plans, "rec": page_rec, "cards": page_cards,
                      "manage": manage_groups}.get(tab, page_overview)()
        except Exception as e:  # noqa: BLE001 - base rota o bloqueada
            return L.page("Expenses", f"Database error: {e}"[:120], [])
        p = L.page("Expenses", STATE["rates"] or "Accounts, budgets, installments, recurring and cards", groups, refresh=30)
        p.update(tabs=[{"key": k, "label": lbl} for k, lbl in TABS], tab=tab, search="Filter transactions…")
        return p


def on_ui(name: str):
    if name == "tab":                             # al cambiar de pestaña se pliegan cuotas y ciclo abiertos
        STATE["plan"] = STATE["card"] = None
    return None


def set_value(key, value):
    return L.fail("Unknown field")


# ════════════════════════════════════════════════════════════════
#  formularios (misma lógica que la TUI)
# ════════════════════════════════════════════════════════════════

def txn_form(key=None, preset=None, vals=None, error=""):
    g = G()
    d = db()
    accts = g.accounts_choices()
    if not accts:
        return L.fail("Create an account first (Manage → New account) or import")
    r = d.q1("SELECT * FROM transactions WHERE id=?", (key,)) if key else None
    p = preset or {}
    if vals is None:
        if r:
            ftype = ("adj_in" if r["type"] == "income" else "adj_out") if r["adjust"] else r["type"]
            vals = {"desc": r["description"], "date": r["date"], "type": ftype, "acc": str(r["account_id"]),
                    "to": str(r["to_account_id"] or "0"), "cat": str(r["category_id"] or "0"), "note": r["note"],
                    "amount": f"{r['orig_amount'] if r['orig_currency'] else r['amount']:g}", "cur": r["orig_currency"] or ""}
        else:
            vals = {"desc": "", "date": date.today().isoformat(), "type": "expense", "acc": accts[0][1], "to": "0",
                    "cat": "0", "note": "", "amount": "", "cur": "", "inst": "1"} | p
    fields = [fld("desc", "Description", vals), fld("amount", "Amount (total, for installments too)", vals),
              fld("cur", "Paid in", vals, g.currency_choices("account's currency")),
              fld("date", "Date (DD/MM/YYYY; for installments, the first one)", vals),
              fld("type", "Type", vals, g.FORM_TYPES), fld("acc", "Account", vals, accts),
              fld("to", "Destination account (transfers only)", vals, [("—", "0")] + accts),
              fld("cat", "Category", vals, g.categories_choices())]
    if not r:
        fields.append(fld("inst", "Installments (1 = single payment)", vals))
    fields.append(fld("note", "Note (optional)", vals))
    title = "Edit transaction" if r else ("New purchase in installments" if str(vals.get("inst", "1")) != "1" else "New transaction")
    if r and r["plan_id"]:
        title += f" · installment {r['inst_no']}"
    return L.form(f"txn:save:{key or 0}", title, fields, error=error)


def txn_save(key: int, v: dict):
    g = G()
    d = db()
    acc_cur = {str(a["id"]): a["currency"] for a in d.q("SELECT id, currency FROM accounts")}
    raw = dict(v)

    def check():
        if not v.get("desc"):
            return "The description is missing"
        if err := g.num_check("Amount", v, "amount", positive=True) or g.date_check("The date", v, "date"):
            return err
        if v["acc"] not in acc_cur:
            return "Pick an account"
        if v["type"] == "transfer" and v["to"] in ("0", v["acc"]):
            return "Pick a different destination account for the transfer"
        if v.get("cur") and d.convert(1, v["cur"], acc_cur[v["acc"]]) is None:
            return f"No exchange rate for {v['cur']} (Manage → Exchange rates)"
        if "inst" in v and (not str(v["inst"]).isdigit() or not 1 <= int(v["inst"]) <= 120):
            return "Installments: a number from 1 to 120"
        if "inst" in v and int(v["inst"]) > 1 and v["type"] != "expense":
            return "Installments only apply to expenses"
        return None

    v.setdefault("note", "")
    v.setdefault("cur", "")
    if err := check():
        return txn_form(key or None, vals=raw, error=err)
    acc = int(v["acc"])
    typ, adjust = {"adj_in": ("income", 1), "adj_out": ("expense", 1)}.get(v["type"], (v["type"], 0))
    entered = float(v["amount"])
    cur = v["cur"] if v["cur"] and v["cur"] != acc_cur[v["acc"]] else ""
    amount = d.convert(entered, cur, acc_cur[v["acc"]]) if cur else entered
    to = int(v["to"]) if typ == "transfer" and v["to"] != "0" else None
    to_amount = d.convert(amount, acc_cur[v["acc"]], acc_cur[v["to"]]) if to and acc_cur[v["to"]] != acc_cur[v["acc"]] else None
    cat = None if adjust else (int(v.get("cat") or 0) or None)
    f = dict(type=typ, account_id=acc, to_account_id=to, category_id=cat, amount=amount, description=v["desc"],
             note=v["note"], date=v["date"], adjust=adjust, orig_amount=entered if cur else None, orig_currency=cur,
             to_amount=to_amount)
    if key:
        d.run(f"UPDATE transactions SET {', '.join(f'{k}=?' for k in f)} WHERE id=?", (*f.values(), key))
        return L.ok(f"{v['desc']} — {money(amount)}")
    if int(v.get("inst") or 1) > 1:
        n = int(v["inst"])
        d.create_plan(v["desc"], acc, cat, amount, n, date.fromisoformat(v["date"]), v["note"])
        return L.ok(f"{v['desc']} — {n} × {money(round(amount / n, 2))}")
    d.add_txn(**f)
    d.con.commit()
    return L.ok(f"{v['desc']} — {money(amount)}")


def plan_form(key: int, vals=None, error=""):
    g = G()
    r = db().q1("SELECT * FROM plans WHERE id=?", (key,))
    vals = vals or {"desc": r["description"], "cat": str(r["category_id"] or "0")}
    return L.form(f"plan:save:{key}", "Edit purchase in installments",
                  [fld("desc", "Description", vals), fld("cat", "Category", vals, g.categories_choices())], error=error,
                  hint="Applies to every installment. To change one amount, edit it in the installments list.")


def rec_form(key=None, vals=None, error=""):
    g = G()
    accts = g.accounts_choices()
    if not accts:
        return L.fail("Create an account first")
    r = db().q1("SELECT * FROM recurring WHERE id=?", (key,)) if key else None
    if vals is None:
        vals = {"desc": r["description"] if r else "", "amount": f"{r['amount']:g}" if r else "", "cur": (r["currency"] or "") if r else "",
                "type": r["type"] if r else "expense", "acc": str(r["account_id"]) if r else accts[0][1],
                "to": str(r["to_account_id"] or "0") if r else "0", "cat": str(r["category_id"] or "0") if r else "0",
                "freq": r["freq"] if r else "monthly", "next": r["next_date"] if r else date.today().isoformat(),
                "end": (r["end_date"] or "") if r else "", "active": str(r["active"]) if r else "1"}
    return L.form(f"rec:save:{key or 0}", "Edit recurring" if r else "New recurring", [
        fld("desc", "Description", vals), fld("amount", "Amount", vals),
        fld("cur", "Currency", vals, g.currency_choices("account's currency")),
        fld("type", "Type", vals, g.FORM_TYPES[:3]), fld("acc", "Account", vals, accts),
        fld("to", "Destination account (transfers only)", vals, [("—", "0")] + accts),
        fld("cat", "Category", vals, g.categories_choices()), fld("freq", "Every", vals, [(f, f) for f in g.FREQS]),
        fld("next", "Next date (DD/MM/YYYY)", vals), fld("end", "End date (optional)", vals),
        fld("active", "Active", vals, [("yes", "1"), ("paused", "0")])],
        error=error, hint="It's posted as a transaction when the date arrives.")


def rec_save(key: int, v: dict):
    g = G()
    d = db()
    raw = dict(v)
    for k in ("cur", "end", "note"):
        v.setdefault(k, "")
    err = None
    if not v.get("desc"):
        err = "The description is missing"
    elif v["type"] == "transfer" and v["to"] in ("0", v["acc"]):
        err = "Pick a different destination account for the transfer"
    else:
        err = (g.num_check("Amount", v, "amount", positive=True) or g.date_check("Next date", v, "next")
               or g.date_check("End date", v, "end", optional=True))
    if err:
        return rec_form(key or None, vals=raw, error=err)
    nxt = date.fromisoformat(v["next"])
    args = (v["desc"], v["type"], int(v["acc"]), int(v["to"]) if v["type"] == "transfer" else None, int(v["cat"]) or None,
            float(v["amount"]), v["cur"], v["freq"], nxt.day, v["next"], v["end"], int(v["active"]))
    if key:
        d.run("UPDATE recurring SET description=?,type=?,account_id=?,to_account_id=?,category_id=?,amount=?,"
              "currency=?,freq=?,day=?,next_date=?,end_date=?,active=? WHERE id=?", (*args, key))
    else:
        d.run("INSERT INTO recurring(description,type,account_id,to_account_id,category_id,amount,currency,"
              "freq,day,next_date,end_date,active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", args)
    posted = d.post_recurring()
    return L.ok(f"Recurring '{v['desc']}' saved" + (f" · {len(posted)} posted" if posted else ""))


def acc_form(key=None, preset=None, vals=None, error=""):
    g = G()
    d = db()
    r = d.q1("SELECT * FROM accounts WHERE id=?", (key,)) if key else None
    p = preset or {}
    pay = [("—", "")] + [c for c in g.accounts_choices() if c[1] != str(key)]
    now = round(d.balances().get(key, 0.0), 2) if key else 0.0
    if vals is None:
        vals = {"name": r["name"] if r else "", "type": r["type"] if r else p.get("type", "bank"),
                "cur": r["currency"] if r else g.MAIN_CURRENCY, "bal": f"{now:.2f}" if r else "0",
                "close": str(r["close_day"]) if r else "0", "due": str(r["pay_day"]) if r else "0",
                "pay": str(r["pay_account_id"] or "") if r else "", "hidden": str(r["hidden"]) if r else "0",
                "notes": (r["notes"] or "") if r else ""}
    bal_label = (("Balance today (a change is saved as a balance adjustment"
                  + ("; cards: negative = what you owe)" if r["type"] == "card" else ")")) if r else "Initial balance")
    return L.form(f"acc:save:{key or 0}", "Edit account" if r else "New account", [
        fld("name", "Name", vals), fld("type", "Type", vals, [(f"{i} {lbl}", k) for k, lbl, i in g.ACCT_TYPES]),
        fld("cur", "Currency", vals, g.currency_choices("—")[1:]), fld("bal", bal_label, vals),
        fld("close", "Credit card: closing day (0 = none)", vals), fld("due", "Credit card: due day", vals),
        fld("pay", "Credit card: paid from", vals, pay), fld("hidden", "Hidden", vals, [("no", "0"), ("yes", "1")]),
        fld("notes", "Notes (optional)", vals)], error=error)


def acc_save(key: int, v: dict):
    g = G()
    d = db()
    raw = dict(v)
    for k in ("notes", "pay", "close", "due"):
        v.setdefault(k, "")
    err = ("The name is missing" if not v.get("name") else g.num_check("Balance", v, "bal")
           or g.day_check("Closing day", v["close"]) or g.day_check("Due day", v["due"]))
    if err:
        return acc_form(key or None, vals=raw, error=err)
    card = v["type"] == "card"
    bal = float(v["bal"] or 0)
    args = (v["name"], v["type"], v["cur"], v["notes"], int(v["close"] or 0) if card else 0, int(v["due"] or 0) if card else 0,
            int(v["pay"]) if card and v["pay"] else None, int(v["hidden"]))
    try:
        if key:
            d.run("UPDATE accounts SET name=?,type=?,currency=?,notes=?,close_day=?,pay_day=?,pay_account_id=?,hidden=? WHERE id=?",
                  (*args, key))
        else:
            d.run("INSERT INTO accounts(name,type,currency,notes,close_day,pay_day,pay_account_id,hidden,init_bal) "
                  "VALUES(?,?,?,?,?,?,?,?,?)", (*args, bal))
    except Exception as e:  # noqa: BLE001 - ej. nombre repetido
        return acc_form(key or None, vals=raw, error=str(e)[:120])
    adj = d.set_balance(key, bal) if key else None
    return L.ok(f"Account '{v['name']}' saved" + (f" · balance adjusted to {money(bal)}" if adj else ""))


def cat_form(key=None, vals=None, error=""):
    r = db().q1("SELECT * FROM categories WHERE id=?", (key,)) if key else None
    if vals is None:
        vals = {"name": r["name"] if r else "", "kind": r["kind"] if r else "expense", "icon": r["icon"] if r else "◻",
                "budget": f"{r['budget']:g}" if r else "0"}
    return L.form(f"cat:save:{key or 0}", "Edit category" if r else "New category", [
        fld("name", "Name", vals), fld("kind", "Kind", vals, [("▼ expense", "expense"), ("▲ income", "income")]),
        fld("icon", "Icon (emoji or symbol)", vals), fld("budget", "Monthly budget (0 = no limit)", vals)],
        error=error, hint="Month budget (per month) is set from the category's actions.")


def cat_save(key: int, v: dict):
    g = G()
    raw = dict(v)
    err = "The name is missing" if not v.get("name") else g.num_check("Budget", v, "budget")
    if err:
        return cat_form(key or None, vals=raw, error=err)
    args = (v["name"], v["kind"], v.get("icon") or "◻", float(v["budget"] or 0))
    try:
        if key:
            db().run("UPDATE categories SET name=?,kind=?,icon=?,budget=? WHERE id=?", (*args, key))
        else:
            db().run("INSERT INTO categories(name,kind,icon,budget) VALUES(?,?,?,?)", args)
    except Exception as e:  # noqa: BLE001
        return cat_form(key or None, vals=raw, error=str(e)[:120])
    return L.ok(f"Category '{v['name']}' saved")


def budget_form(key: int, vals=None, error=""):
    g = G()
    c = db().q1("SELECT * FROM categories WHERE id=?", (key,))
    m = STATE["month"]
    ym = m.strftime("%Y-%m")
    cur = db().q1("SELECT amount FROM budgets WHERE category_id=? AND month=?", (key, ym))
    vals = vals or {"amount": f"{cur['amount']:g}" if cur else ""}
    return L.form(f"cat:budgetsave:{key}", f"Budget · {c['name']} · {g.MONTHS[m.month - 1]} {m.year}",
                  [fld("amount", f"Amount for this month (empty = default {money(c['budget'])})", vals)], error=error,
                  hint="The month is the one shown in Overview.")


def statement_form(key: int, vals=None, error=""):
    g = G()
    a = db().q1("SELECT * FROM accounts WHERE id=?", (key,))
    ci = db().card_status(a, date.today())
    if not ci:
        return L.fail(f"{a['name']} has no closing day: set it with Edit")
    vals = vals or {"closed": f"{ci['closed']:.2f}", "current": f"{ci['current']:.2f}", "note": ""}
    return L.form(f"card:stsave:{key}", f"Statement · {a['name']}", [
        fld("closed", f"Closed statement ({g.ddmm(ci['prev_close'])} → {g.ddmm(ci['last_close'])}), total billed", vals),
        fld("current", f"Current cycle so far ({g.ddmm(ci['last_close'])} → {g.ddmm(ci['next_close'])})", vals),
        fld("note", "Note (optional)", vals)], error=error,
        hint=f"Paid since the closing: {money(ci['paid'])} (payments are transfers: Pay). "
             "Differences with what's recorded are saved as adjustments.")


def cur_form(code=None, vals=None, error=""):
    g, rates = G(), __import__("expenses_rates")
    r = db().q1("SELECT * FROM currencies WHERE code=?", (code,)) if code else None
    src = rates.effective_source(r["code"], r["source"]) if r else "manual"
    if vals is None:
        vals = {"code": r["code"] if r else "", "src": src, "rate": f"{r['rate']:g}" if r and r["rate"] else ""}
    return L.form(f"cur:save:{code or ''}", "Exchange rate", [
        fld("code", "Code (USD, EUR, BRL…)", vals), fld("src", "Source", vals, rates.source_choices(vals.get("code", "").upper())),
        fld("rate", f"Rate: 1 unit = how many {g.MAIN_CURRENCY} (manual only)", vals)], error=error,
        hint="Automatic rates are refreshed every time Expenses opens (and with Update exchange rates).")


def cur_save(code: str, v: dict):
    g = G()
    raw = dict(v)
    d = db()
    v["code"] = (v.get("code") or "").strip()
    err = None
    if not v["code"]:
        err = "The code is missing"
    elif not code and d.q1("SELECT 1 FROM currencies WHERE code=?", (v["code"].upper(),)):
        err = f"{v['code'].upper()} already exists"
    else:
        err = g.num_check("Rate", v, "rate", positive=v["src"] == "manual")
    if err:
        return cur_form(code or None, vals=raw, error=err)
    c = v["code"].upper()
    rate = float(v["rate"] or 0)
    d.run("INSERT INTO currencies(code, rate, source, updated) VALUES(?,?,?,?) ON CONFLICT(code) DO UPDATE SET source=excluded.source"
          + (", rate=excluded.rate, updated=excluded.updated" if v["src"] == "manual" else ""),
          (c, rate, v["src"], "manual" if v["src"] == "manual" else ""))
    if v["src"] == "manual":
        return L.ok(f"{c} = {money(rate, g.MAIN_CURRENCY)} (manual)")
    update_rates()
    return L.ok(f"{c}: updating from DolarAPI…")


# ════════════════════════════════════════════════════════════════
#  acciones
# ════════════════════════════════════════════════════════════════

def delete(what: str, key, msg: str, sql: str, text):
    if not L.yes(text):
        return L.confirm(f"{what}:del:{key}", f"Delete {dict(txn='transaction', acc='account', cat='category', plan='purchase', rec='recurring', cur='currency')[what]}",
                         msg, ok_label="Delete")
    db().run(sql, (key,))
    return L.ok("Deleted")


def act(key: str, text=None):
    with LOCK:
        try:
            return _act(key, text)
        except Exception as e:  # noqa: BLE001
            return L.fail(f"Error: {e}"[:160])


def _act(key: str, text):
    g = G()
    d = db()
    kind, _, rest = key.partition(":")
    op, _, arg = rest.partition(":")
    v = L.parse_form(text) if text and text.startswith("{") else {}

    if kind == "month":
        m = STATE["month"]
        STATE["month"] = date.today().replace(day=1) if rest == "0" else g.add_months(m, int(rest), 1)
        return L.ok()
    if kind == "rates":
        return L.ok(update_rates(wait=True))
    if kind == "csv":
        path = Path.home() / f"expenses-export-{date.today().isoformat()}.csv"
        path.write_text(d.export_csv(), encoding="utf-8")
        return L.ok(f"Exported → {path}")
    if kind == "import":
        dl = Path.home() / "Downloads"
        default = dl / "money_android.sqlite"
        if text is None:
            return L.form("import", "Import from Money Manager", [
                {"name": "path", "label": "BACKUP FILE (.SQLITE EXPORTED FROM THE APP)", "text": str(default if default.exists() else dl) + ("" if default.exists() else "/")}],
                hint="Nothing is written until you review the list and apply it.", ok_label="Analyze")
        path = Path(v.get("path", "")).expanduser()
        if not path.is_file():
            return L.form("import", "Import from Money Manager", [{"name": "path", "label": "BACKUP FILE", "text": v.get("path", "")}],
                          error="File not found", ok_label="Analyze")
        mm = __import__("expenses_import")
        try:
            an = mm.analyze(path, d)
        except Exception as e:  # noqa: BLE001
            return L.fail(f"Can't read {path.name}: {e}"[:160])
        if not an.items:
            return L.ok(f"Nothing new · {sum(an.same.values())} already imported" + (f" · {an.ignored} ignored" if an.ignored else ""))
        STATE["import"] = an
        UI["tab"] = "manage"
        return L.ok(f"{len(an.items)} items to review")

    if kind == "imp":
        an = STATE["import"]
        if not an:
            return L.ok()
        if op == "toggle":
            it = an.items[int(arg)]
            it.include = not it.include
            return L.ok()
        if op in ("all", "none"):
            for it in an.items:
                if it.kind == arg:
                    it.include = op == "all"
            return L.ok()
        if op == "cancel":
            STATE["import"] = None
            return L.ok("Import cancelled")
        if op == "apply":
            STATE["import"] = None
            try:
                st = __import__("expenses_import").apply(an, d)
            except Exception as e:  # noqa: BLE001
                return L.fail(f"Import failed, nothing changed: {e}"[:160])
            posted = d.post_recurring()
            parts = [f"{st[k]} {k}" for k in ("transactions", "updated", "accounts", "categories", "recurring", "budgets",
                                               "currencies") if st.get(k)]
            return L.ok("Imported: " + (", ".join(parts) or "nothing") + (f" · {len(posted)} recurring posted" if posted else ""))

    if kind == "txn":
        if op == "new":
            preset = {}
            if arg == "inst":
                preset["inst"] = "3"
            elif arg.startswith("acc:"):
                preset["acc"] = arg[4:]
            return txn_form(preset=preset)
        if op == "edit":
            return txn_form(int(arg))
        if op == "save":
            return txn_save(int(arg), v)
        if op == "del":
            r = d.q1("SELECT description, amount, plan_id FROM transactions WHERE id=?", (int(arg),))
            if not r:
                return L.ok()
            msg = f"Delete '{r['description']}' ({money(r['amount'])})?"
            if r["plan_id"]:
                msg += "\nOnly this installment: to delete the whole purchase use the Installments tab."
            return delete("txn", int(arg), msg, "DELETE FROM transactions WHERE id=?", text)

    if kind == "plan":
        if op == "open":
            STATE["plan"] = None if STATE["plan"] == int(arg) else int(arg)
            return L.ok()
        if op == "edit":
            return plan_form(int(arg))
        if op == "save":
            if not v.get("desc"):
                return plan_form(int(arg), vals=v, error="The description is missing")
            cat = int(v.get("cat") or 0) or None
            d.run("UPDATE plans SET description=?, category_id=? WHERE id=?", (v["desc"], cat, int(arg)))
            d.run("UPDATE transactions SET description=?, category_id=? WHERE plan_id=?", (v["desc"], cat, int(arg)))
            return L.ok(f"'{v['desc']}' saved (all installments)")
        if op == "del":
            r = d.q1("SELECT description, n FROM plans WHERE id=?", (int(arg),))
            return delete("plan", int(arg), f"Delete '{r['description']}' and its {r['n']} installments?",
                          "DELETE FROM plans WHERE id=?", text)

    if kind == "rec":
        if op == "new":
            return rec_form()
        if op == "edit":
            return rec_form(int(arg))
        if op == "save":
            return rec_save(int(arg), v)
        if op == "toggle":
            d.run("UPDATE recurring SET active = 1 - active WHERE id=?", (int(arg),))
            return L.ok()
        if op == "post":
            posted = d.post_recurring()
            return L.ok(f"Posted: {', '.join(posted)}" if posted else "Nothing due")
        if op == "del":
            r = d.q1("SELECT description FROM recurring WHERE id=?", (int(arg),))
            return delete("rec", int(arg), f"Delete recurring '{r['description']}'? Already posted transactions stay.",
                          "DELETE FROM recurring WHERE id=?", text)

    if kind == "acc":
        if op == "new":
            return acc_form(preset={"type": "card"} if arg == "card" else None)
        if op == "edit":
            return acc_form(int(arg))
        if op == "save":
            return acc_save(int(arg), v)
        if op == "del":
            r = d.q1("SELECT name FROM accounts WHERE id=?", (int(arg),))
            return delete("acc", int(arg), f"Delete account '{r['name']}' and ALL its transactions?",
                          "DELETE FROM accounts WHERE id=?", text)

    if kind == "cat":
        if op == "new":
            return cat_form()
        if op == "edit":
            return cat_form(int(arg))
        if op == "save":
            return cat_save(int(arg), v)
        if op == "budget":
            return budget_form(int(arg))
        if op == "budgetsave":
            if err := g.num_check("Amount", v, "amount"):
                return budget_form(int(arg), vals=v, error=err)
            ym = STATE["month"].strftime("%Y-%m")
            if v["amount"]:
                d.run("INSERT OR REPLACE INTO budgets(category_id, month, amount) VALUES(?,?,?)", (int(arg), ym, float(v["amount"])))
            else:
                d.run("DELETE FROM budgets WHERE category_id=? AND month=?", (int(arg), ym))
            c = d.q1("SELECT name FROM categories WHERE id=?", (int(arg),))
            return L.ok(f"Budget of {c['name']} for {ym} saved")
        if op == "del":
            r = d.q1("SELECT name FROM categories WHERE id=?", (int(arg),))
            return delete("cat", int(arg), f"Delete category '{r['name']}'? Its transactions stay, without category.",
                          "DELETE FROM categories WHERE id=?", text)

    if kind == "card":
        k = int(arg)
        if op == "open":
            STATE["card"] = None if STATE["card"] == k else k
            return L.ok()
        if op == "statement":
            return statement_form(k)
        if op == "stsave":
            a = d.q1("SELECT * FROM accounts WHERE id=?", (k,))
            ci = d.card_status(a, date.today())
            v.setdefault("note", "")
            if err := g.num_check("Closed statement", v, "closed") or g.num_check("Current cycle", v, "current"):
                return statement_form(k, vals=v, error=err)
            n = 0
            if v["closed"] and d.adjust(k, ci["closed"] - float(v["closed"]), ci["last_close"].isoformat(), "Statement adjustment", v["note"]):
                n += 1
            if v["current"] and d.adjust(k, ci["current"] - float(v["current"]), None, "Cycle adjustment", v["note"]):
                n += 1
            return L.ok(f"{a['name']}: {n} adjustment(s) saved" if n else "Nothing to adjust")
        if op == "pay":
            a = d.q1("SELECT * FROM accounts WHERE id=?", (k,))
            ci = d.card_status(a, date.today())
            amount = max(0.0, ci["closed"] - ci["paid"]) if ci else max(0.0, -d.balances().get(k, 0))
            return txn_form(preset={"type": "transfer", "to": str(k), "acc": str(a["pay_account_id"] or ""),
                                    "amount": f"{amount:.2f}", "date": date.today().isoformat(),
                                    "desc": f"PAGO TARJETA {a['name']} " + (g.MONTHS[ci["last_close"].month - 1].upper() if ci else "")})

    if kind == "cur":
        if op == "new":
            return cur_form()
        if op == "edit":
            return cur_form(arg)
        if op == "save":
            return cur_save(arg, v)
        if op == "del":
            if d.q1("SELECT 1 FROM accounts WHERE currency=?", (arg,)):
                return L.fail(f"{arg} is used by an account")
            return delete("cur", arg, f"Delete currency {arg}?", "DELETE FROM currencies WHERE code=?", text)
    return L.ok()
