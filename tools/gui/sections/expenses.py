"""Expenses (GUI): app de finanzas personales sobre la base de la TUI tools/expenses_tui.py.

La dibuja config/quickshell/Finance.qml (no SectionPage): get() devuelve datos estructurados de la
vista pedida (UI["view"]: overview, transactions, budgets, cards, plans, scheduled, reports) más la
barra lateral de cuentas; los formularios, confirmaciones y validaciones son los de siempre (act() →
L.form / L.confirm, misma lógica que la TUI). La vista Manage embebe la sección Finances
(manage_groups()/act() de acá, que también usa Settings).
Base: la de expenses_db.py (~/.local/state/dotfiles/expenses/expenses.db o $EXPENSES_DB). Al abrir
pide las cotizaciones en un hilo y después genera los fijos vencidos, igual que la TUI.
"""

from __future__ import annotations

import json
import sys
import threading
import calendar
from datetime import date, timedelta
from pathlib import Path

from . import _lib as L

sys.path.insert(0, str(L.TOOLS))

UI: dict = {}
LOCK = threading.RLock()
STATE = {"month": date.today().replace(day=1), "plan": None, "card": None, "import": None,
         "rates": "", "rates_started": False}
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


def manage_groups() -> list:
    g, rates = G(), __import__("expenses_rates")
    d = db()
    groups = import_groups()
    bal = d.balances()
    accs = [L.item(f"acc:edit:{a['id']}", f"{g.ACCT_ICONS.get(a['type'], '◻')} {a['name']}",
                   sub=f"{dict((k, l) for k, l, _ in g.ACCT_TYPES).get(a['type'], a['type'])} · {a['currency']}"
                   + (" · hidden" if a["hidden"] else ""), right=money(bal.get(a["id"], 0), a["currency"]), on=not a["hidden"],
                   actions=[L.action(f"acc:balance:{a['id']}", "Set balance"), L.action(f"acc:edit:{a['id']}", "Edit"),
                            L.action(f"acc:del:{a['id']}", "Delete", True)])
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


# ════════════════════════════════════════════════════════════════
#  vistas (datos para quickshell/Finance.qml)
# ════════════════════════════════════════════════════════════════

VIEWS = ["overview", "transactions", "budgets", "cards", "plans", "scheduled", "reports", "manage"]
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_FULL = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
              "November", "December"]


def iso(d) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else (d or "")


def dlabel(d) -> str:
    """Mon 09 Nov (con el año si no es el actual)."""
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{WD[d.weekday()]} {d.day:02d} {MON[d.month - 1]}" + (f" {d.year}" if d.year != date.today().year else "")


def short_date(d) -> str:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return f"{d.day:02d} {MON[d.month - 1]}" + (f" {d.year % 100:02d}" if d.year != date.today().year else "")


def days_to(d) -> int:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return (d - date.today()).days


def when(d) -> str:
    """today, tomorrow, in 5 days, 3 days ago."""
    n = days_to(d)
    return "today" if n == 0 else "tomorrow" if n == 1 else "yesterday" if n == -1 else \
        f"in {n} days" if n > 0 else f"{-n} days ago"


def compact(v: float) -> str:
    """$1.25M / $350K / $980 (para ejes y tarjetas chicas)."""
    a, sg = abs(v or 0), "-" if (v or 0) < -0.005 else ""
    if a >= 1e6:
        return f"{sg}${a / 1e6:.2f}M"
    if a >= 1e4:
        return f"{sg}${a / 1e3:.0f}K"
    return f"{sg}${a:,.0f}"


def ic(icon, name) -> str:
    """Ícono de la categoría o, si no tiene (las importadas traen ◻), su inicial."""
    return icon if icon and icon != "◻" else (name or "?")[:1].upper()


def ym_of(d: date) -> str:
    return d.strftime("%Y-%m")


def month_list(end: date, n: int) -> list[date]:
    return [G().add_months(end, i - n + 1, 1) for i in range(n)]


def month_totals(d, months: list[date]) -> dict[str, dict]:
    lo, hi = ym_of(months[0]), ym_of(months[-1])
    out = {ym_of(m): {"income": 0.0, "expense": 0.0} for m in months}
    for r in d.q("""SELECT substr(date,1,7) AS ym, type, SUM(amount) AS s FROM transactions
                    WHERE adjust=0 AND type IN ('income','expense') AND substr(date,1,7) BETWEEN ? AND ?
                    GROUP BY 1, 2""", (lo, hi)):
        out[r["ym"]][r["type"]] = float(r["s"] or 0)
    return out


def cat_spend(d, ym: str, kind: str = "expense") -> dict:
    """{category_id: gasto del mes} (None = sin categoría)."""
    return {r[0]: float(r[1]) for r in d.q("""SELECT category_id, SUM(amount) FROM transactions
                                             WHERE adjust=0 AND type=? AND date LIKE ? GROUP BY 1""", (kind, ym + "%"))}


TXN_COLS = """SELECT tx.*, a.name AS aname, a.currency, a.type AS atype, c.name AS cname, c.icon AS cicon,
                     ta.name AS taname, p.n AS pn
              FROM transactions tx
              JOIN accounts a ON a.id = tx.account_id
              LEFT JOIN categories c ON c.id = tx.category_id
              LEFT JOIN accounts ta ON ta.id = tx.to_account_id
              LEFT JOIN plans p ON p.id = tx.plan_id"""


def txn(r, today: str) -> dict:
    t = r["type"]
    sign = "-" if t == "expense" else "+" if t == "income" else ""
    cat = "Balance adjustment" if r["adjust"] else (r["cname"] or ("Transfer" if t == "transfer" else "No category"))
    acct = r["aname"] + (f" → {r['taname']}" if r["taname"] else "")
    extra = []
    if r["orig_currency"]:
        extra.append(f"{r['orig_amount']:,.2f} {r['orig_currency']}")
    if r["fee_of"]:
        extra.append("fee")
    if r["recurring_id"]:
        extra.append("recurring")
    return {"id": r["id"], "desc": r["description"] or "(no description)", "type": t, "cat": cat,
            "icon": "±" if r["adjust"] else ("⇄" if t == "transfer" else ic(r["cicon"], r["cname"] or r["description"])), "acct": acct,
            "amount": f"{sign}{money(r['amount'], r['currency'] if r['currency'] != G().MAIN_CURRENCY else '')}",
            "value": float(r["amount"]), "future": r["date"] > today, "date": r["date"], "dlabel": short_date(r["date"]),
            "inst": f"{r['inst_no']}/{r['pn']}" if r["plan_id"] else "", "note": r["note"] or "", "extra": " · ".join(extra),
            "card": r["atype"] == "card"}


def sidebar(d) -> dict:
    g = G()
    bal = d.balances()
    labels = {k: lbl for k, lbl, _ in g.ACCT_TYPES}
    order = [k for k, _, _ in g.ACCT_TYPES]
    groups: dict[str, dict] = {}
    nw = assets = debt = 0.0
    for a in d.q("SELECT * FROM accounts WHERE hidden=0 ORDER BY sort, name"):
        b = bal.get(a["id"], 0.0)
        conv = d.convert(b, a["currency"], g.MAIN_CURRENCY) or 0.0
        nw += conv
        if conv < 0:
            debt -= conv
        elif a["type"] != "card":
            assets += conv
        grp = groups.setdefault(a["type"], {"key": a["type"], "name": labels.get(a["type"], a["type"]).capitalize(),
                                            "total": 0.0, "accounts": []})
        grp["total"] += conv
        grp["accounts"].append({"id": a["id"], "name": a["name"], "icon": g.ACCT_ICONS.get(a["type"], "◻"),
                                "balance": money(b), "cur": a["currency"] if a["currency"] != g.MAIN_CURRENCY else "",
                                "neg": b < -0.005, "card": a["type"] == "card"})
    out = sorted(groups.values(), key=lambda x: order.index(x["key"]) if x["key"] in order else 99)
    for grp in out:
        grp["totalFmt"] = compact(grp["total"])
    return {"net": money(nw), "netShort": compact(nw), "assets": compact(assets), "debt": compact(debt),
            "groups": out}


def recurring_occurrences(d, lo: date, hi: date) -> list[dict]:
    """Ocurrencias de los fijos activos entre lo y hi (todavía no generadas)."""
    g = G()
    out = []
    for r in d.q("""SELECT r.*, a.name AS aname, a.currency AS acur, a.type AS atype, c.name AS cname, c.icon AS cicon
                    FROM recurring r JOIN accounts a ON a.id = r.account_id
                    LEFT JOIN categories c ON c.id = r.category_id WHERE r.active=1"""):
        x = date.fromisoformat(r["next_date"])
        end = date.fromisoformat(r["end_date"]) if r["end_date"] else None
        n = 0
        while x <= hi and (end is None or x <= end) and n < 40:
            if x >= lo:
                cur = r["currency"] or r["acur"]
                sign = "-" if r["type"] == "expense" else "+" if r["type"] == "income" else ""
                out.append({"date": x.isoformat(), "kind": "recurring", "id": r["id"], "desc": r["description"],
                            "sub": f"{r['freq']} · {r['aname']}", "icon": ic(r["cicon"], r["cname"] or r["description"]), "type": r["type"],
                            "amount": f"{sign}{money(r['amount'], cur if cur != g.MAIN_CURRENCY else '')}",
                            "value": d.convert(r["amount"], cur, g.MAIN_CURRENCY) or 0.0, "card": r["atype"] == "card"})
            x = __import__("expenses_db").next_date(x, r["freq"], r["day"])
            n += 1
    return out


def card_info(d, a, today: date, bal: dict) -> dict:
    g = G()
    st = d.card_status(a, today)
    debt = -bal.get(a["id"], 0.0)
    out = {"id": a["id"], "name": a["name"], "hidden": bool(a["hidden"]), "debt": money(debt) if debt > 0.005 else money(0),
           "owes": debt > 0.005, "closeDay": a["close_day"], "payDay": a["pay_day"], "ok": st is not None}
    if not st:
        return out
    left = max(0.0, st["closed"] - st["paid"])
    span = max(1, (st["next_close"] - st["last_close"]).days)
    out |= {"lastClose": short_date(st["last_close"]), "nextClose": short_date(st["next_close"]),
            "lastDue": short_date(st["last_due"]), "nextDue": short_date(st["next_due"]),
            "toClose": days_to(st["next_close"]), "toDue": days_to(st["last_due"]), "toNextDue": days_to(st["next_due"]),
            "closeWhen": when(st["next_close"]), "dueWhen": when(st["last_due"]),
            "closed": money(st["closed"]), "paid": money(st["paid"]), "left": money(left), "leftValue": left,
            "settled": left <= 0.5, "duePast": st["last_due"] < today,
            "current": money(st["current"]), "upcoming": money(st["upcoming"]),
            "cyclePct": min(1.0, max(0.0, (today - st["last_close"]).days / span)),
            "cycleRange": f"{short_date(st['last_close'] + timedelta(days=1))} → {short_date(st['next_close'])}",
            "closedRange": f"{short_date(st['prev_close'] + timedelta(days=1))} → {short_date(st['last_close'])}"}
    return out


def v_overview(d, month: date) -> dict:
    g = G()
    today = date.today()
    ym = ym_of(month)
    months = month_list(month, 6)
    tot = month_totals(d, months)
    cur = tot[ym]
    spend = cat_spend(d, ym)
    cats = {c["id"]: c for c in d.q("SELECT * FROM categories")}
    by = sorted(((cats[k]["name"] if k in cats else "No category", ic(cats[k]["icon"], cats[k]["name"]) if k in cats else "?", v)
                 for k, v in spend.items() if v > 0), key=lambda x: -x[2])
    total_sp = sum(v for *_, v in by) or 1
    top = [{"name": n, "icon": i, "amount": compact(v), "full": money(v), "pct": v / total_sp} for n, i, v in by[:6]]
    if len(by) > 6:
        rest = sum(v for *_, v in by[6:])
        top.append({"name": f"{len(by) - 6} more", "icon": "…", "amount": compact(rest), "full": money(rest), "pct": rest / total_sp})
    budget = spent = 0.0
    for c in cats.values():
        if c["kind"] == "expense" and (b := d.budget_for(c["id"], ym)) > 0:
            budget += b
            spent += spend.get(c["id"], 0.0)
    # próximos 30 días: fijos, cuotas/gastos fuera de tarjeta y vencimientos de tarjetas
    hi = date.fromordinal(today.toordinal() + 30)
    up = [o for o in recurring_occurrences(d, today, hi) if not o["card"]]
    t = today.isoformat()
    for r in d.q(TXN_COLS + " WHERE tx.date > ? AND tx.date <= ? AND a.type<>'card' AND tx.recurring_id IS NULL "
                            "ORDER BY tx.date", (t, hi.isoformat())):
        x = txn(r, t)
        up.append({"date": r["date"], "kind": "installment" if r["plan_id"] else "scheduled", "id": r["id"],
                   "desc": x["desc"] + (f" ({x['inst']})" if x["inst"] else ""), "sub": f"{x['cat']} · {x['acct']}",
                   "icon": x["icon"], "type": r["type"], "amount": x["amount"], "value": x["value"]})
    bal = d.balances()
    cards = []
    for a in d.q("SELECT * FROM accounts WHERE type='card' AND hidden=0 ORDER BY sort, name"):
        ci = card_info(d, a, today, bal)
        cards.append(ci)
        st = d.card_status(a, today)
        if st:
            if ci["leftValue"] > 0.5 and st["last_due"] >= today:
                up.append({"date": st["last_due"].isoformat(), "kind": "card", "id": a["id"], "desc": f"{a['name']} statement",
                           "sub": f"closed {short_date(st['last_close'])}", "icon": "💳", "type": "expense",
                           "amount": f"-{money(ci['leftValue'])}", "value": ci["leftValue"]})
            if st["next_due"] <= hi:
                up.append({"date": st["next_due"].isoformat(), "kind": "card", "id": a["id"], "desc": f"{a['name']} statement",
                           "sub": f"closes {short_date(st['next_close'])} · so far", "icon": "💳", "type": "expense",
                           "amount": f"-{money(st['current'])}", "value": st["current"]})
    up.sort(key=lambda o: o["date"])
    for o in up:
        o["when"] = when(o["date"])
        o["dlabel"] = short_date(o["date"])
    recent = [txn(r, t) for r in d.q(TXN_COLS + " WHERE tx.date <= ? ORDER BY tx.date DESC, tx.time DESC, tx.id DESC LIMIT 8", (t,))]
    inc, exp = cur["income"], cur["expense"]
    sched = 0.0
    if ym == ym_of(today):                        # mes en curso: lo de fecha futura (cuotas, fijos) va aparte
        sched = float(d.val("SELECT SUM(amount) FROM transactions WHERE adjust=0 AND type='expense' AND date LIKE ? "
                            "AND date > ?", (ym + "%", t)))
        exp -= sched
    prev_avg = [tot[ym_of(m)]["expense"] for m in months[:-1] if tot[ym_of(m)]["expense"] or tot[ym_of(m)]["income"]]
    return {
        "kpis": [
            {"label": "Income", "value": money(inc), "sub": f"{MONTH_FULL[month.month - 1]}", "tone": "ok"},
            {"label": "Expenses", "value": money(exp), "tone": "",
             "sub": (f"+{compact(sched)} scheduled · " if sched > 0.005 else "")
             + (f"avg {compact(sum(prev_avg) / len(prev_avg))} / month" if prev_avg else "")},
            {"label": "Net", "value": ("+" if inc >= exp else "-") + money(abs(inc - exp)),
             "sub": f"saved {((inc - exp) / inc * 100):.0f}% of income" if inc > 0 else "no income yet", "tone": "ok" if inc >= exp else "error"},
            {"label": "Budget", "value": f"{spent / budget * 100:.0f}%" if budget else "—",
             "sub": f"{compact(spent)} of {compact(budget)}" if budget else "no budgets set",
             "tone": "" if not budget else "error" if spent > budget else "warn" if spent > budget * pace(month) else "ok",
             "pct": spent / budget if budget else 0}],
        "categories": top, "trend": [{"label": MON[m.month - 1], "income": tot[ym_of(m)]["income"], "expense": tot[ym_of(m)]["expense"],
                                      "sel": ym_of(m) == ym} for m in months],
        "upcoming": up[:12], "upcomingTotal": money(sum(o["value"] for o in up if o["type"] == "expense")),
        "cards": cards, "recent": recent}


def pace(month: date) -> float:
    """Qué parte del mes pasó (1 si ya terminó, 0 si es futuro)."""
    today = date.today()
    if ym_of(month) < ym_of(today):
        return 1.0
    if ym_of(month) > ym_of(today):
        return 0.0
    return today.day / calendar.monthrange(today.year, today.month)[1]


def v_transactions(d, month: date) -> dict:
    ym, t = ym_of(month), date.today().isoformat()
    where, args = ["tx.date LIKE ?"], [ym + "%"]
    f = {k: UI.get(k) or "" for k in ("q", "ftype", "facc", "fcat")}
    if f["ftype"] in ("expense", "income", "transfer"):
        where.append("tx.type=? AND tx.adjust=0")
        args.append(f["ftype"])
    elif f["ftype"] == "adjust":
        where.append("tx.adjust=1")
    if str(f["facc"]).isdigit():
        where.append("(tx.account_id=? OR tx.to_account_id=?)")
        args += [int(f["facc"])] * 2
    if str(f["fcat"]).lstrip("-").isdigit():
        if int(f["fcat"]) == 0:
            where.append("tx.category_id IS NULL AND tx.type='expense'")
        else:
            where.append("tx.category_id=?")
            args.append(int(f["fcat"]))
    days: dict[str, dict] = {}
    inc = exp = 0.0
    n = 0
    q = f["q"].strip().lower()
    for r in d.q(TXN_COLS + f" WHERE {' AND '.join(where)} ORDER BY tx.date DESC, tx.time DESC, tx.id DESC", tuple(args)):
        if q and not any(q in (x or "").lower() for x in (r["description"], r["aname"], r["cname"], r["note"], r["taname"])):
            continue
        x = txn(r, t)
        day = days.setdefault(r["date"], {"date": r["date"], "label": dlabel(r["date"]), "when": when(r["date"]) if abs(days_to(r["date"])) <= 1 else "",
                                          "future": r["date"] > t, "net": 0.0, "items": []})
        day["items"].append(x)
        if not r["adjust"]:
            if r["type"] == "expense":
                exp += r["amount"]
                day["net"] -= r["amount"]
            elif r["type"] == "income":
                inc += r["amount"]
                day["net"] += r["amount"]
        n += 1
    for day in days.values():
        day["netFmt"] = ("+" if day["net"] > 0 else "") + money(day["net"]) if abs(day["net"]) > 0.005 else ""
    accs = [{"label": "All accounts", "value": ""}] + [{"label": a["name"], "value": str(a["id"])}
                                                      for a in d.q("SELECT id, name FROM accounts ORDER BY hidden, sort, name")]
    cats = [{"label": "All categories", "value": ""}, {"label": "No category", "value": "0"}] + [
        {"label": f"{c['icon']} {c['name']}", "value": str(c["id"])} for c in d.q("SELECT * FROM categories ORDER BY kind DESC, sort, name")]
    return {"days": list(days.values()), "count": n, "income": money(inc), "expense": money(exp),
            "filters": f, "accounts": accs, "cats": cats}


def v_budgets(d, month: date) -> dict:
    g = G()
    ym = ym_of(month)
    spend = cat_spend(d, ym)
    prev = [ym_of(g.add_months(month, -i, 1)) for i in (1, 2, 3)]
    avg = {r[0]: float(r[1]) / 3 for r in d.q(f"""SELECT category_id, SUM(amount) FROM transactions
            WHERE adjust=0 AND type='expense' AND substr(date,1,7) IN (?,?,?) GROUP BY 1""", tuple(prev))}
    p = pace(month)
    rows, unb = [], []
    tb = ts = 0.0
    for c in d.q("SELECT * FROM categories WHERE kind='expense' ORDER BY sort, name"):
        b = d.budget_for(c["id"], ym)
        sp = spend.get(c["id"], 0.0)
        ov = d.q1("SELECT 1 FROM budgets WHERE category_id=? AND month=?", (c["id"], ym)) is not None
        row = {"id": c["id"], "icon": ic(c["icon"], c["name"]), "name": c["name"], "spent": money(sp), "spentShort": compact(sp),
               "avg": compact(avg.get(c["id"], 0.0)), "override": ov, "default": money(c["budget"])}
        if b > 0:
            tb += b
            ts += sp
            pct = sp / b
            row |= {"budget": money(b), "left": money(b - sp), "over": sp > b, "pct": pct,
                    "tone": "error" if sp > b else "warn" if pct > max(p, 0.0001) + 0.05 and p < 1 else "ok",
                    "status": f"{money(sp - b)} over" if sp > b else f"{money(b - sp)} left"}
            rows.append(row)
        else:
            row |= {"value": sp}
            unb.append(row)
    unb.sort(key=lambda r: -r["value"])
    nocat = spend.get(None, 0.0)
    return {"rows": rows, "unbudgeted": unb, "noCategory": money(nocat) if nocat else "",
            "total": money(tb), "spent": money(ts), "left": money(tb - ts), "over": ts > tb, "pct": ts / tb if tb else 0,
            "pace": p, "paceLabel": "" if p in (0.0, 1.0) else f"{p * 100:.0f}% of the month gone",
            "suggest": compact(sum(avg.values()))}


def v_cards(d) -> dict:
    today = date.today()
    bal = d.balances()
    cards = [card_info(d, a, today, bal) for a in d.q("SELECT * FROM accounts WHERE type='card' ORDER BY hidden, sort, name")]
    sel = UI.get("card")
    ids = [c["id"] for c in cards]
    sel = sel if sel in ids else (ids[0] if ids else None)
    detail = None
    if sel is not None:
        a = d.q1("SELECT * FROM accounts WHERE id=?", (sel,))
        st = d.card_status(a, today)
        stm = d.card_statements(a, today)
        t = today.isoformat()
        cyc = [txn(r, t) for r in d.q(TXN_COLS + " WHERE tx.account_id=? AND tx.type<>'transfer' AND tx.date > ? AND tx.date <= ? "
                                                 "ORDER BY tx.date DESC, tx.time DESC, tx.id DESC",
                                      (sel, st["last_close"].isoformat(), st["next_close"].isoformat()))] if st else []
        mx = max([s["amount"] for s in stm] + [1])
        known = {c.isoformat() for c, _ in d.card_closings(sel)}
        pay = d.q1("SELECT name FROM accounts WHERE id=?", (a["pay_account_id"],)) if a["pay_account_id"] else None
        detail = {"id": sel, "name": a["name"], "payFrom": pay["name"] if pay else "",
                  "statements": [{"label": MON[s["close"].month - 1], "close": short_date(s["close"]), "due": short_date(s["due"]),
                                  "amount": compact(s["amount"]), "full": money(s["amount"]), "inst": money(s["installments"]),
                                  "h": max(0.0, s["amount"]) / mx, "hi": max(0.0, s["installments"]) / mx, "state": s["state"],
                                  "known": s["close"].isoformat() in known} for s in stm],
                  "cycle": cyc,
                  "closings": [{"close": short_date(c), "due": short_date(dd) if dd else "—", "key": c.isoformat(),
                                "past": c < today} for c, dd in d.card_closings(sel)][-8:]}
    return {"cards": cards, "selected": sel, "detail": detail}


def v_plans(d) -> dict:
    g = G()
    today = date.today()
    t = today.isoformat()
    this_m, next_m = ym_of(today), ym_of(g.add_months(today, 1, 1))
    active, done = [], []
    pend = 0.0
    for p in d.q("""
            SELECT p.*, a.name AS aname, c.name AS cname, c.icon AS cicon,
                   SUM(CASE WHEN t.date <= ? THEN 1 ELSE 0 END) AS paid, COUNT(t.id) AS cnt,
                   SUM(CASE WHEN t.date > ? THEN t.amount ELSE 0 END) AS remaining,
                   MIN(CASE WHEN t.date > ? THEN t.date END) AS nxt, MAX(t.date) AS last,
                   (SELECT amount FROM transactions WHERE plan_id=p.id ORDER BY inst_no DESC LIMIT 1) AS each_
            FROM plans p JOIN accounts a ON a.id = p.account_id
            LEFT JOIN categories c ON c.id = p.category_id
            LEFT JOIN transactions t ON t.plan_id = p.id
            GROUP BY p.id ORDER BY last, p.description""", (t, t, t)):
        paid = (p["paid"] or 0) + (p["n"] - (p["cnt"] or 0))
        rem = float(p["remaining"] or 0)
        pend += rem
        row = {"id": p["id"], "desc": p["description"], "acct": p["aname"], "cat": p["cname"] or "No category",
               "icon": ic(p["cicon"], p["cname"] or p["description"]), "paid": paid, "n": p["n"], "pct": paid / p["n"] if p["n"] else 1,
               "each": money(p["each_"] or 0), "total": money(p["total"]), "left": money(rem),
               "next": short_date(p["nxt"]) if p["nxt"] else "", "end": f"{MON[int(p['last'][5:7]) - 1]} {p['last'][:4]}" if p["last"] else "",
               "open": STATE["plan"] == p["id"]}
        if row["open"]:
            row["items"] = [{"id": r["id"], "no": f"{r['inst_no']}/{p['n']}", "date": short_date(r["date"]), "amount": money(r["amount"]),
                             "paid": r["date"] <= t} for r in d.q("SELECT * FROM transactions WHERE plan_id=? ORDER BY inst_no, date", (p["id"],))]
        (active if rem > 0.005 else done).append(row)
    months = [g.add_months(today, i, 1) for i in range(12)]
    by = {r[0]: float(r[1]) for r in d.q("""SELECT substr(date,1,7), SUM(amount) FROM transactions
                                           WHERE plan_id IS NOT NULL AND substr(date,1,7) BETWEEN ? AND ? GROUP BY 1""",
                                        (ym_of(months[0]), ym_of(months[-1])))}
    mx = max(list(by.values()) + [1])
    return {"pending": money(pend), "thisMonth": money(by.get(this_m, 0.0)), "nextMonth": money(by.get(next_m, 0.0)),
            "count": len(active), "active": active, "done": done[-12:][::-1], "doneCount": len(done),
            "commit": [{"label": MON[m.month - 1], "amount": compact(by.get(ym_of(m), 0.0)), "h": by.get(ym_of(m), 0.0) / mx}
                       for m in months]}


def v_scheduled(d) -> dict:
    g = G()
    today = date.today()
    rows = []
    tot = {"expense": 0.0, "income": 0.0}
    for r in d.q("""SELECT r.*, a.name AS aname, a.currency AS acur, ta.name AS taname, c.name AS cname, c.icon AS cicon
                    FROM recurring r JOIN accounts a ON a.id = r.account_id
                    LEFT JOIN accounts ta ON ta.id = r.to_account_id
                    LEFT JOIN categories c ON c.id = r.category_id
                    ORDER BY r.active DESC, r.next_date, r.description"""):
        cur = r["currency"] or r["acur"]
        conv = d.convert(r["amount"], cur, g.MAIN_CURRENCY) or 0.0
        k = {"monthly": 1, "weekly": 52 / 12, "yearly": 1 / 12, "daily": 30.4}.get(r["freq"], 1)
        if r["active"] and r["type"] in tot:
            tot[r["type"]] += conv * k
        sign = "-" if r["type"] == "expense" else "+" if r["type"] == "income" else ""
        rows.append({"id": r["id"], "desc": r["description"], "type": r["type"], "active": bool(r["active"]),
                     "amount": f"{sign}{money(r['amount'], cur if cur != g.MAIN_CURRENCY else '')}", "freq": r["freq"],
                     "acct": r["aname"] + (f" → {r['taname']}" if r["taname"] else ""), "cat": r["cname"] or "",
                     "icon": "⇄" if r["type"] == "transfer" else ic(r["cicon"], r["cname"] or r["description"]),
                     "next": short_date(r["next_date"]), "when": when(r["next_date"]) if r["active"] else "paused",
                     "soon": r["active"] and 0 <= days_to(r["next_date"]) <= 7,
                     "ends": short_date(r["end_date"]) if r["end_date"] else ""})
    occ = recurring_occurrences(d, today, date.fromordinal(today.toordinal() + 30))
    occ.sort(key=lambda o: o["date"])
    for o in occ:
        o["when"], o["dlabel"] = when(o["date"]), short_date(o["date"])
    return {"rows": rows, "out": money(tot["expense"]), "in": money(tot["income"]),
            "net": ("+" if tot["income"] >= tot["expense"] else "-") + money(abs(tot["income"] - tot["expense"])),
            "upcoming": occ[:14], "active": sum(1 for r in rows if r["active"])}


def v_reports(d, month: date) -> dict:
    g = G()
    first = d.val("SELECT MIN(date) FROM transactions WHERE adjust=0", default="")
    months = [m for m in month_list(month, 12) if not first or ym_of(m) >= first[:7]] or [month]
    tot = month_totals(d, months)
    mx = max([max(v["income"], v["expense"]) for v in tot.values()] + [1])
    trend = [{"label": MON[m.month - 1], "income": tot[ym_of(m)]["income"] / mx, "expense": tot[ym_of(m)]["expense"] / mx,
              "inc": compact(tot[ym_of(m)]["income"]), "exp": compact(tot[ym_of(m)]["expense"]), "sel": m == month}
             for m in months]
    ym = ym_of(month)
    spend = cat_spend(d, ym)
    prev = [ym_of(g.add_months(month, -i, 1)) for i in (1, 2, 3)]
    avg = {r[0]: float(r[1]) / 3 for r in d.q("""SELECT category_id, SUM(amount) FROM transactions
            WHERE adjust=0 AND type='expense' AND substr(date,1,7) IN (?,?,?) GROUP BY 1""", tuple(prev))}
    cats = {c["id"]: c for c in d.q("SELECT * FROM categories")}
    keys = sorted(set(spend) | set(avg), key=lambda k: -max(spend.get(k, 0.0), avg.get(k, 0.0)))
    cmx = max([max(spend.get(k, 0.0), avg.get(k, 0.0)) for k in keys] + [1])
    comp = []
    for k in keys[:10]:
        a, s = avg.get(k, 0.0), spend.get(k, 0.0)
        comp.append({"name": cats[k]["name"] if k in cats else "No category", "icon": ic(cats[k]["icon"], cats[k]["name"]) if k in cats else "?",
                     "now": s / cmx, "avg": a / cmx, "nowFmt": compact(s), "avgFmt": compact(a),
                     "delta": f"{(s - a) / a * 100:+.0f}%" if a > 0 else "new", "up": s > a})
    t = date.today().isoformat()
    top = [txn(r, t) for r in d.q(TXN_COLS + " WHERE tx.date LIKE ? AND tx.type='expense' AND tx.adjust=0 "
                                             "ORDER BY tx.amount DESC LIMIT 8", (ym + "%",))]
    acc = d.q("""SELECT a.name, SUM(tx.amount) AS s FROM transactions tx JOIN accounts a ON a.id=tx.account_id
                 WHERE tx.date LIKE ? AND tx.type='expense' AND tx.adjust=0 GROUP BY a.id ORDER BY s DESC""", (ym + "%",))
    amx = max([float(r["s"]) for r in acc] + [1])
    y = [tot[ym_of(m)] for m in months]
    ti, te = sum(v["income"] for v in y), sum(v["expense"] for v in y)
    span = f"{len(months)} months"
    return {"trend": trend, "comp": comp, "top": top,
            "byAccount": [{"name": r["name"], "amount": compact(r["s"]), "h": float(r["s"]) / amx} for r in acc],
            "year": {"income": compact(ti), "expense": compact(te), "net": compact(ti - te), "span": span,
                     "avgExp": compact(te / len(months)), "rate": f"{(ti - te) / ti * 100:.0f}%" if ti > 0 else "—"}}


def get() -> dict:
    with LOCK:
        if not STATE["rates_started"]:
            STATE["rates_started"] = True
            update_rates()
        view = UI.get("view") if UI.get("view") in VIEWS else "overview"
        if STATE["import"]:
            view = UI["view"] = "manage"
        d, m = db(), STATE["month"]
        try:
            data = {"overview": lambda: v_overview(d, m), "transactions": lambda: v_transactions(d, m),
                    "budgets": lambda: v_budgets(d, m), "cards": lambda: v_cards(d), "plans": lambda: v_plans(d),
                    "scheduled": lambda: v_scheduled(d), "reports": lambda: v_reports(d, m),
                    "manage": lambda: {}}[view]()
            side = sidebar(d)
        except Exception as e:  # noqa: BLE001 - base rota o bloqueada
            return {"ok": False, "msg": f"Database error: {e}"[:160]}
        return {"ok": True, "view": view, "data": data, "sidebar": side, "status": STATE["rates"], "rates": rates_line(),
                "month": ym_of(m), "monthLabel": f"{MONTH_FULL[m.month - 1]} {m.year}", "isThisMonth": m == date.today().replace(day=1),
                "currency": G().MAIN_CURRENCY, "refresh": 30000}


def on_ui(name: str):
    if name == "view":                            # al cambiar de vista se pliega la compra abierta
        STATE["plan"] = None
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
    # Orden de carga rápida: lo que siempre se completa primero; el destino solo en transferencias
    is_tr = vals.get("type") == "transfer"
    fields = [fld("desc", "Description", vals), fld("amount", "Amount (total, for installments too)", vals),
              fld("acc", "From account" if is_tr else "Account", vals, accts)]
    if is_tr or r:
        fields.append(fld("to", "Destination account (transfers only)", vals, [("—", "0")] + accts))
    if not is_tr:
        fields.append(fld("cat", "Category", vals, g.categories_choices()))
    fields.append(fld("date", "Date (DD/MM/YYYY; for installments, the first one)", vals))
    if not r and not is_tr:
        fields.append(fld("inst", "Installments (1 = single payment)", vals))
    fields += [fld("type", "Type", vals, g.FORM_TYPES), fld("cur", "Paid in", vals, g.currency_choices("account's currency")),
               fld("note", "Note (optional)", vals)]
    title = "Edit transaction" if r else ("New purchase in installments" if str(vals.get("inst", "1")) != "1" else
                                          {"income": "New income", "transfer": "New transfer"}.get(vals.get("type"), "New expense"))
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

    for k, dv in (("note", ""), ("cur", ""), ("to", "0"), ("cat", "0")):
        v.setdefault(k, dv)
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
        fld("close", "Credit card: usual closing day (0 = none)", vals), fld("due", "Credit card: usual due day", vals),
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


def balance_form(key: int, vals=None, error=""):
    """Saldo de hoy de una cuenta (en una tarjeta, lo que se debe): la diferencia se guarda como ajuste."""
    d = db()
    a = d.q1("SELECT * FROM accounts WHERE id=?", (key,))
    now = round(d.balances().get(key, 0.0), 2)
    card = a["type"] == "card"
    if vals is None:
        vals = {"bal": f"{(-now if card else now):.2f}", "note": ""}
    label = (f"Owed today in {a['currency']} (as the bank shows it; negative = credit in your favor)" if card
             else f"Balance today in {a['currency']}")
    return L.form(f"acc:balsave:{key}", f"Set balance · {a['name']}", [fld("bal", label, vals), fld("note", "Note (optional)", vals)],
                  error=error, ok_label="Adjust",
                  hint=f"Now: {money(-now if card else now, a['currency'])}{' owed' if card else ''}. The difference is saved as a "
                       "balance adjustment dated today; the other transactions stay as they are.")


def balance_save(key: int, v: dict):
    d = db()
    a = d.q1("SELECT * FROM accounts WHERE id=?", (key,))
    v.setdefault("note", "")
    raw = dict(v)
    if not str(v.get("bal", "")).strip():
        return balance_form(key, vals=raw, error="The balance is missing")
    if err := G().num_check("Balance", v, "bal"):
        return balance_form(key, vals=raw, error=err)
    card = a["type"] == "card"
    target = -float(v["bal"]) if card else float(v["bal"])
    before = d.balances().get(key, 0.0)
    if not d.set_balance(key, target, note=v["note"]):
        return L.ok(f"{a['name']} already has that balance")
    diff = target - before
    return L.ok(f"{a['name']}: {'+' if diff > 0 else '-'}{money(abs(diff))} adjustment · "
                + (f"owes {money(-target)}" if card else f"balance {money(target, a['currency'])}"))


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
                  hint="The month is the one shown at the top.")


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


def closing_form(key: int, vals=None, error=""):
    a = db().q1("SELECT * FROM accounts WHERE id=?", (key,))
    st = db().card_status(a, date.today())
    if vals is None:
        vals = {"close": st["next_close"].isoformat() if st else "", "due": st["next_due"].isoformat() if st else ""}
    return L.form(f"card:closesave:{key}", f"Closing dates · {a['name']}", [
        fld("close", "Closing date (DD/MM/YYYY)", vals), fld("due", "Due date (optional)", vals)], error=error,
        hint="The dates printed on the statement (next closing / next due). They replace the usual closing day "
             f"({a['close_day'] or '—'}) for that statement only; the others keep it.")


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
            elif arg.startswith("type:"):
                preset["type"] = arg[5:]
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
        if op == "balance":
            return balance_form(int(arg))
        if op == "balsave":
            return balance_save(int(arg), v)
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
        k = int(arg.partition(":")[0])
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
        if op == "closing":
            return closing_form(k)
        if op == "closesave":
            v.setdefault("due", "")
            if err := g.date_check("Closing date", v, "close") or g.date_check("Due date", v, "due", optional=True):
                return closing_form(k, vals=v, error=err)
            if v["due"] and v["due"] <= v["close"]:
                return closing_form(k, vals=v, error="The due date has to be after the closing date")
            d.run("INSERT OR REPLACE INTO card_closings(account_id, close_date, due_date) VALUES(?,?,?)", (k, v["close"], v["due"]))
            return L.ok(f"Closing {g.ddmm(v['close'])} saved" + (f" · due {g.ddmm(v['due'])}" if v["due"] else ""))
        if op == "closedel":
            acc_id, _, day = arg.partition(":")
            if not L.yes(text):
                return L.confirm(key, "Delete closing date", f"Delete the closing of {day}? That statement goes back to the usual closing day.",
                                 ok_label="Delete")
            d.run("DELETE FROM card_closings WHERE account_id=? AND close_date=?", (int(acc_id), day))
            return L.ok("Closing date deleted")
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
