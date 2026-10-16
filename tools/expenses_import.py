#!/usr/bin/env python3
"""
expenses_import.py — importa un backup de Money Manager (Realbyte) al gestor de gastos
════════════════════════════════════════════════════════════════
uso  : python3 expenses_import.py money_android.sqlite            (solo muestra)
       python3 expenses_import.py money_android.sqlite --apply    (aplica lo marcado por defecto)
       (o desde la TUI o Settings → Finances: tecla i)

En la app: Settings → Backup → exportar como archivo .sqlite (money_android.sqlite).

El backup se abre en solo lectura. La TUI es la fuente de verdad: el import
compara cada registro de la app (por su uid, guardado en `mm_uid`) con lo que
ya hay y arma una lista para revisar antes de aplicar:

  new      no está en la TUI                          → marcado
  dup      parece algo cargado a mano en la TUI        → sin marcar; si queda
           (misma cuenta, tipo y monto, fecha ±1 día)    así se vincula, y el
                                                         próximo import lo saltea
  changed  ya importado, pero cambió en la app desde   → sin marcar (la TUI manda;
           ese import (no cuenta lo editado en la TUI)    si queda así, no se vuelve
                                                         a ofrecer ese cambio)

Lo desmarcado se recuerda (tabla mm_ignored) y no se vuelve a ofrecer. Lo ya
importado y sin cambios no se muestra. Las cuentas, categorías y planes
de cuotas que use algo importado se crean siempre. Antes de aplicar se guarda
una copia de la base (expenses.db.bak-…).
════════════════════════════════════════════════════════════════
"""

import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from expenses_db import MAIN_CURRENCY, Database, add_months  # noqa: E402
from expenses_rates import effective_source  # noqa: E402

# Grupos de cuentas de Money Manager (ASSETGROUP.TYPE) → tipo de cuenta
GROUP_TYPES = {1: "bank", 2: "card", 3: "debit", 4: "savings", 5: "loan", 6: "prepaid",
               7: "other", 8: "investments", 9: "bank", 10: "other", 11: "cash"}
DO_TYPES = {0: "income", 1: "expense", 3: "transfer"}       # 4 = la otra mitad de la transferencia
REPEAT_FREQS = {1: "monthly"}                                # el único que aparece en los backups vistos
ADJUST_CTG = "-4"                                            # "Modificar saldo"
INST_RE = re.compile(r"\((\d+)/(\d+)\)")


@dataclass
class Item:
    kind: str                     # account | category | currency | budget | recurring | txn
    status: str                   # new | dup | changed
    key: str                      # uid en Money Manager
    label: str
    date: str = ""
    account: str = ""
    amount: Optional[float] = None
    currency: str = ""
    detail: str = ""              # por qué es duplicado / qué cambió
    include: bool = True
    data: dict = field(default_factory=dict)
    local_id: Optional[int] = None


@dataclass
class Analysis:
    path: Path
    items: list[Item]
    same: dict[str, int]          # ya importados sin cambios, por tipo
    plans: dict[str, dict]        # cardDivideUid → datos del plan de cuotas
    links: dict[str, dict]        # cuentas / categorías que ya existían por nombre: tipo → {uid: id local}
    skipped: list[str]
    ignored: int = 0              # desmarcados en imports anteriores

    def count(self, status: str) -> int:
        return sum(1 for i in self.items if i.status == status)


def _ms_to_dt(ms) -> datetime:
    return datetime.fromtimestamp(int(float(ms)) / 1000)


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _sig(*parts) -> str:
    """Firma de cómo está un registro en la app (para ver si cambió desde el import)."""
    return "|".join("" if p is None else f"{p:.2f}" if isinstance(p, float) else str(p) for p in parts)


def _sig_diff(old: str, new: str, names: tuple[str, ...]) -> str:
    a, b = old.split("|"), new.split("|")
    return ", ".join(n for n, x, y in zip(names, a, b) if x != y) or "changed"


TXN_SIG = ("date", "amount", "description", "account", "type", "category")
REC_SIG = ("description", "amount", "account", "category", "currency")


def _open_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ════════════════════════════════════════════════════════════════
#  ANÁLISIS
# ════════════════════════════════════════════════════════════════
def analyze(path: Path, db: Database) -> Analysis:
    mm = _open_ro(path)
    try:
        return _analyze(mm, path, db)
    finally:
        mm.close()


def _analyze(mm: sqlite3.Connection, path: Path, db: Database) -> Analysis:
    items: list[Item] = []
    same = {k: 0 for k in ("account", "category", "currency", "budget", "recurring", "txn")}
    skipped: list[str] = []
    links: dict[str, dict] = {"account": {}, "category": {}}
    ignored = {(r["kind"], r["mm_uid"]) for r in db.q("SELECT kind, mm_uid FROM mm_ignored")}
    n_ignored = 0

    # ── monedas ──
    cur_iso = {r["uid"]: r["ISO"] for r in mm.execute("SELECT uid, ISO FROM CURRENCY")}
    main = mm.execute("SELECT ISO FROM CURRENCY WHERE IS_MAIN_CURRENCY=1").fetchone()
    if main and main["ISO"] != MAIN_CURRENCY:
        skipped.append(f"main currency in the app is {main['ISO']}, here {MAIN_CURRENCY}: amounts kept as-is")
    for r in mm.execute("SELECT * FROM CURRENCY WHERE IS_DEL=0 AND IS_MAIN_CURRENCY=0"):
        local = db.q1("SELECT rate, source FROM currencies WHERE code=?", (r["ISO"],))
        if local is not None and effective_source(r["ISO"], local["source"]) != "manual":
            same["currency"] += 1                     # se cotiza de internet: la de la app no aplica
        elif ("currency", f"{r['ISO']}={r['RATE']}") in ignored:
            n_ignored += 1
        elif local is None:
            items.append(Item("currency", "new", r["uid"], r["ISO"], amount=r["RATE"], currency=MAIN_CURRENCY,
                              data={"code": r["ISO"], "rate": r["RATE"]}))
        elif abs(local["rate"] - r["RATE"]) > 1e-6:
            items.append(Item("currency", "changed", r["uid"], r["ISO"], amount=r["RATE"],
                              currency=MAIN_CURRENCY, include=False,
                              detail=f"rate here {local['rate']:g}, in the app {r['RATE']:g}",
                              data={"code": r["ISO"], "rate": r["RATE"]}))
        else:
            same["currency"] += 1

    # ── cuentas ──
    groups = {r["uid"]: r["TYPE"] for r in mm.execute("SELECT uid, TYPE FROM ASSETGROUP")}
    acc_name: dict[str, str] = {}
    acc_cur: dict[str, str] = {}
    used_names: set[str] = set()
    # Con nombres repetidos se queda con el nombre la cuenta más usada; las otras llevan " (2)"
    for r in mm.execute("""SELECT a.*, (SELECT count(*) FROM INOUTCOME i WHERE i.assetUid=a.uid) AS ntx
                           FROM ASSETS a ORDER BY ntx DESC, ORDERSEQ, ID"""):
        name = r["NIC_NAME"].strip()
        base, n = name, 2
        while name.casefold() in used_names:          # Money Manager permite nombres repetidos
            name, n = f"{base} ({n})", n + 1
        used_names.add(name.casefold())
        acc_name[r["uid"]] = name
        acc_cur[r["uid"]] = cur_iso.get(r["currencyUid"], MAIN_CURRENCY)
        typ = GROUP_TYPES.get(groups.get(r["groupUid"]), "other")
        if db.q1("SELECT 1 FROM accounts WHERE mm_uid=?", (r["uid"],)):
            same["account"] += 1
            continue
        local = db.q1("SELECT id FROM accounts WHERE lower(name)=lower(?) AND mm_uid IS NULL", (name,))
        if local:
            links["account"][r["uid"]] = local["id"]
            same["account"] += 1
            continue
        card = typ == "card"
        items.append(Item("account", "new", r["uid"], name, currency=acc_cur[r["uid"]],
                          detail=f"{typ}" + (f", closes {r['CARD_DAY_FIN']}, due {r['CARD_DAY_PAY']}"
                                             if card else ""),
                          data={"name": name, "type": typ, "currency": acc_cur[r["uid"]],
                                "notes": (r["ZDATA1"] or "").strip(), "sort": r["ORDERSEQ"] or 0,
                                "hidden": 1 if str(r["ZDATA"]) == "1" else 0,
                                "close_day": int(_num(r["CARD_DAY_FIN"])) if card else 0,
                                "pay_day": int(_num(r["CARD_DAY_PAY"])) if card else 0,
                                "pay_account": (r["cardAssetUid"] or None) if card else None}))

    # ── movimientos (antes que las categorías: define cuáles se usan) ──
    pairs = {r["txUidTrans"]: r for r in mm.execute(
        "SELECT * FROM INOUTCOME WHERE DO_TYPE='4' AND IFNULL(IS_DEL,0)=0 AND IFNULL(txUidTrans,'')<>''")}
    rows = mm.execute("SELECT * FROM INOUTCOME WHERE IFNULL(IS_DEL,0)=0 AND DO_TYPE IN ('0','1','3') "
                      "ORDER BY ZDATE").fetchall()
    used_ctg = {r["ctgUid"] for r in rows if r["ctgUid"] not in (None, "", ADJUST_CTG)}
    rec_rows = mm.execute("SELECT * FROM REPEATTRANSACTION WHERE IFNULL(IS_DEL,0)=0").fetchall()
    used_ctg |= {r["ctgUid"] for r in rec_rows if r["ctgUid"]}

    # ── categorías ──
    cats = {r["uid"]: r for r in mm.execute("SELECT * FROM ZCATEGORY")}

    def cat_name(uid: str) -> str:
        r = cats[uid]
        parent = cats.get(r["pUid"]) if r["pUid"] not in (None, "", "0") else None
        return f"{parent['NAME']} › {r['NAME']}" if parent else r["NAME"]

    for uid, r in sorted(cats.items(), key=lambda kv: (kv[1]["TYPE"], kv[1]["ORDERSEQ"] or 0)):
        sub = r["pUid"] not in (None, "", "0")
        if (r["C_IS_DEL"] or sub) and uid not in used_ctg:
            continue                                  # borradas y subcategorías sin uso
        kind = "income" if r["TYPE"] == 0 else "expense"
        name = cat_name(uid)
        if db.q1("SELECT 1 FROM categories WHERE mm_uid=?", (uid,)):
            same["category"] += 1
            continue
        local = db.q1("SELECT id FROM categories WHERE lower(name)=lower(?) AND kind=? AND mm_uid IS NULL",
                      (name, kind))
        if local:
            links["category"][uid] = local["id"]
            same["category"] += 1
            continue
        items.append(Item("category", "new", uid, name, detail=kind,
                          data={"name": name, "kind": kind, "sort": r["ORDERSEQ"] or 0}))

    def local_cat(uid: Optional[str]) -> Optional[int]:
        if not uid:
            return None
        row = db.q1("SELECT id FROM categories WHERE mm_uid=?", (uid,))
        return row["id"] if row else links["category"].get(uid)

    def local_acc(uid: Optional[str]) -> Optional[int]:
        if not uid:
            return None
        row = db.q1("SELECT id FROM accounts WHERE mm_uid=?", (uid,))
        return row["id"] if row else links["account"].get(uid)

    # ── presupuestos (solo el mensual por defecto: BUDGET_PERIOD 0) ──
    for r in mm.execute("""
            SELECT b.targetUid, a.AMOUNT, a.BUDGET_PERIOD FROM BUDGET b
            JOIN BUDGET_AMOUNT a ON a.budgetUid = b.uid
            WHERE IFNULL(b.IS_DEL,0)=0 AND IFNULL(a.IS_DEL,0)=0 AND b.DO_TYPE=1 AND IFNULL(b.IS_TOTAL,0)=0"""):
        if r["targetUid"] not in cats:
            continue
        if r["BUDGET_PERIOD"] not in (0, None):
            skipped.append(f"budget of {cats[r['targetUid']]['NAME']} for period {r['BUDGET_PERIOD']}")
            continue
        cid = local_cat(r["targetUid"])
        cur = db.val("SELECT budget FROM categories WHERE id=?", (cid,)) if cid else 0
        it = Item("budget", "new", r["targetUid"], cat_name(r["targetUid"]), amount=r["AMOUNT"],
                  currency=MAIN_CURRENCY, data={"ctg": r["targetUid"], "amount": r["AMOUNT"]})
        if cid and abs(cur - r["AMOUNT"]) < 0.005:
            same["budget"] += 1
            continue
        if ("budget", f"{r['targetUid']}={r['AMOUNT']}") in ignored:
            n_ignored += 1
            continue
        if cid and cur:
            it.status, it.include, it.detail = "changed", False, f"here {cur:,.2f}"
        items.append(it)

    # ── fijos (recurrentes) ──
    for r in rec_rows:
        typ = DO_TYPES.get(int(r["DO_TYPE"]), "expense")
        if r["toAssetUid"]:
            typ = "transfer"
        nd = _ms_to_dt(r["NEXT_DATE"]).date()
        cur = cur_iso.get(r["currencyUid"], MAIN_CURRENCY)
        desc = (r["PAYEE"] or r["MEMO"] or "").strip() or "(no description)"
        data = {"description": desc, "type": typ, "account": r["assetUid"], "to_account": r["toAssetUid"] or None,
                "ctg": r["ctgUid"] or None, "amount": r["AMOUNT_SUB"],
                "currency": "" if cur == acc_cur.get(r["assetUid"]) else cur,
                "freq": REPEAT_FREQS.get(r["REPEAT_TYPE"], "monthly"), "day": nd.day,
                "next_date": nd.isoformat(),
                "end_date": _ms_to_dt(r["END_DATE"]).date().isoformat() if r["END_DATE"] else ""}
        data["sig"] = _sig(desc, float(r["AMOUNT_SUB"]), r["assetUid"], r["ctgUid"], data["currency"])
        it = Item("recurring", "new", r["uid"], desc, date=nd.isoformat(), account=acc_name.get(r["assetUid"], "?"),
                  amount=r["AMOUNT_SUB"], currency=cur, data=data)
        local = db.q1("SELECT * FROM recurring WHERE mm_uid=?", (r["uid"],))
        if local:
            if local["mm_sig"] in (None, data["sig"]):
                same["recurring"] += 1
                continue
            it.status, it.include, it.local_id = "changed", False, local["id"]
            it.detail = "changed: " + _sig_diff(local["mm_sig"], data["sig"], REC_SIG)
        elif ("recurring", r["uid"]) in ignored:
            n_ignored += 1
            continue
        else:
            dup = db.q1("SELECT * FROM recurring WHERE lower(description)=lower(?) AND mm_uid IS NULL", (desc,))
            if dup:
                it.status, it.include, it.local_id = "dup", False, dup["id"]
                it.detail = f"same name as recurring #{dup['id']} ({dup['amount']:,.2f})"
        items.append(it)

    # ── planes de cuotas ──
    plans: dict[str, dict] = {}
    for r in rows:
        m = INST_RE.search(r["CARD_DIVIDE_MONTH_STR"] or "")
        if r["cardDivideUid"] and m:
            d = _ms_to_dt(r["ZDATE"]).date()
            p = plans.setdefault(r["cardDivideUid"], {"description": (r["ZCONTENT"] or "").strip(),
                                                      "account": r["assetUid"], "ctg": r["ctgUid"] or None,
                                                      "n": int(m[2]), "total": 0.0, "first": None})
            p["total"] = round(p["total"] + _num(r["AMOUNT_ACCOUNT"] or r["ZMONEY"]), 2)
            if m[1] == "1":
                p["first"], p["real_first"] = d, True
            elif not p.get("real_first"):             # la cuota 1 falta: se deduce de las demás
                first = add_months(d, 1 - int(m[1]))
                p["first"] = min(p["first"] or first, first)

    # ── movimientos ──
    consumed: set[int] = set()
    for r in rows:
        typ = DO_TYPES[int(r["DO_TYPE"])]
        dt = _ms_to_dt(r["ZDATE"])
        amount = _num(r["AMOUNT_ACCOUNT"]) or _num(r["ZMONEY"])
        cur = cur_iso.get(r["currencyUid"], MAIN_CURRENCY)
        acur = acc_cur.get(r["assetUid"], MAIN_CURRENCY)
        desc = (r["ZCONTENT"] or "").strip()
        m = INST_RE.search(r["CARD_DIVIDE_MONTH_STR"] or "")
        plan = r["cardDivideUid"] if (r["cardDivideUid"] and m) else None
        data = {"account": r["assetUid"], "to_account": r["toAssetUid"] if typ == "transfer" else None,
                "ctg": None if r["ctgUid"] in (None, "", ADJUST_CTG) else r["ctgUid"],
                "type": typ, "amount": amount, "description": desc or ("transfer" if typ == "transfer" else "—"),
                "note": (r["ZDATA"] or "").strip(), "date": dt.date().isoformat(), "time": dt.strftime("%H:%M"),
                "orig_amount": _num(r["IN_ZMONEY"]) if cur != acur else None,
                "orig_currency": cur if cur != acur else "",
                "to_amount": None, "adjust": 1 if r["ctgUid"] == ADJUST_CTG else 0,
                "plan": plan, "inst_no": int(m[1]) if plan else None, "fee_key": r["txUidFee"] or None}
        if typ == "transfer":
            pair = pairs.get(r["txUidTrans"])
            if pair is not None and acc_cur.get(r["toAssetUid"]) != acur:
                data["to_amount"] = _num(pair["AMOUNT_ACCOUNT"])
        label = data["description"] + (f" {m[0]}" if plan else "")
        if data["adjust"]:
            label = f"{label} (balance adjust)"
        account = acc_name.get(r["assetUid"], "?") + (f" → {acc_name.get(r['toAssetUid'], '?')}"
                                                       if typ == "transfer" else "")
        it = Item("txn", "new", r["uid"], label, date=data["date"], account=account,
                  amount=-amount if typ == "expense" else amount, currency=acur, data=data)

        data["sig"] = _sig(data["date"], float(amount), data["description"], r["assetUid"], typ, data["ctg"])
        local = db.q1("SELECT id, mm_sig FROM transactions WHERE mm_uid=?", (r["uid"],))
        if local:
            if local["mm_sig"] in (None, data["sig"]):
                same["txn"] += 1
                continue
            it.status, it.include, it.local_id = "changed", False, local["id"]
            it.detail = "changed: " + _sig_diff(local["mm_sig"], data["sig"], TXN_SIG)
        elif ("txn", r["uid"]) in ignored:
            n_ignored += 1
            continue
        else:
            acc_id = local_acc(r["assetUid"])
            if acc_id:
                d0 = dt.date().toordinal()
                for c in db.q("""SELECT id, date, description FROM transactions
                                 WHERE account_id=? AND type=? AND abs(amount-?)<0.005 AND mm_uid IS NULL""",
                              (acc_id, typ, amount)):
                    if c["id"] not in consumed and abs(date.fromisoformat(c["date"]).toordinal() - d0) <= 1:
                        consumed.add(c["id"])
                        it.status, it.include, it.local_id = "dup", False, c["id"]
                        it.detail = f"looks like #{c['id']} {c['date']} '{c['description']}'"
                        break
        items.append(it)

    return Analysis(path, items, same, plans, links, skipped, n_ignored)


# ════════════════════════════════════════════════════════════════
#  APLICAR
# ════════════════════════════════════════════════════════════════
def apply(an: Analysis, db: Database) -> dict[str, int]:
    """Aplica los ítems marcados (los `dup` sin marcar se vinculan). Todo en
    una sola transacción: si algo falla no queda nada a medias."""
    backup = db.backup()
    con = db.con
    stats = {"backup": str(backup)}
    inc = [i for i in an.items if i.include]
    by_kind = lambda k: [i for i in an.items if i.kind == k]  # noqa: E731
    def ignore(kind: str, uid: str) -> None:
        con.execute("INSERT OR IGNORE INTO mm_ignored(kind, mm_uid) VALUES(?,?)", (kind, uid))

    try:
        con.execute("BEGIN")
        n = 0
        # monedas
        for it in by_kind("currency"):
            if it.include:
                con.execute("INSERT INTO currencies(code, rate) VALUES(?,?) "
                            "ON CONFLICT(code) DO UPDATE SET rate=excluded.rate",
                            (it.data["code"], it.data["rate"]))
                n += 1
            else:
                ignore("currency", f"{it.data['code']}={it.data['rate']}")
        stats["currencies"] = n

        # cuentas: vínculos por nombre + las nuevas que hagan falta
        for uid, lid in an.links["account"].items():
            con.execute("UPDATE accounts SET mm_uid=? WHERE id=? AND mm_uid IS NULL", (uid, lid))
        need_acc = {i.key for i in by_kind("account") if i.include}
        for i in inc:
            if i.kind in ("txn", "recurring"):
                need_acc |= {i.data["account"], i.data.get("to_account")} - {None}
        acc_items = {i.key: i for i in by_kind("account")}
        n = 0
        for uid in sorted(need_acc & acc_items.keys(), key=lambda u: acc_items[u].data["sort"]):
            d = acc_items[uid].data
            con.execute("INSERT INTO accounts(name, type, currency, notes, sort, hidden, close_day, pay_day, mm_uid) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (d["name"], d["type"], d["currency"], d["notes"], d["sort"], d["hidden"],
                         d["close_day"], d["pay_day"], uid))
            n += 1
        stats["accounts"] = n

        def acc(uid: Optional[str]) -> Optional[int]:
            if not uid:
                return None
            row = con.execute("SELECT id FROM accounts WHERE mm_uid=?", (uid,)).fetchone()
            return row["id"] if row else None

        for uid in need_acc & acc_items.keys():       # tarjeta → cuenta con la que se paga
            if (pay := acc_items[uid].data["pay_account"]) and acc(pay):
                con.execute("UPDATE accounts SET pay_account_id=? WHERE mm_uid=?", (acc(pay), uid))

        # categorías
        for uid, lid in an.links["category"].items():
            con.execute("UPDATE categories SET mm_uid=? WHERE id=? AND mm_uid IS NULL", (uid, lid))
        need_cat = {i.key for i in by_kind("category") if i.include}
        for i in inc:
            if i.kind in ("txn", "recurring", "budget"):
                need_cat |= {i.data.get("ctg")} - {None}
        for p in an.plans.values():
            need_cat |= {p["ctg"]} - {None}
        n = 0
        for it in by_kind("category"):
            if it.key in need_cat:
                con.execute("INSERT INTO categories(name, kind, sort, mm_uid) VALUES(?,?,?,?)",
                            (it.data["name"], it.data["kind"], it.data["sort"], it.key))
                n += 1
        stats["categories"] = n

        def cat(uid: Optional[str]) -> Optional[int]:
            if not uid:
                return None
            row = con.execute("SELECT id FROM categories WHERE mm_uid=?", (uid,)).fetchone()
            return row["id"] if row else None

        # presupuestos
        n = 0
        for it in by_kind("budget"):
            if it.include and (cid := cat(it.data["ctg"])):
                con.execute("UPDATE categories SET budget=? WHERE id=?", (it.data["amount"], cid))
                n += 1
            elif not it.include:
                ignore("budget", f"{it.data['ctg']}={it.data['amount']}")
        stats["budgets"] = n

        # fijos
        n = 0
        for it in by_kind("recurring"):
            d = it.data
            vals = (d["description"], d["type"], acc(d["account"]), acc(d["to_account"]), cat(d["ctg"]),
                    d["amount"], d["currency"])
            if it.status == "changed":
                if it.include:
                    con.execute("UPDATE recurring SET description=?, type=?, account_id=?, to_account_id=?, "
                                "category_id=?, amount=?, currency=? WHERE id=?", (*vals, it.local_id))
                    n += 1
                con.execute("UPDATE recurring SET mm_sig=? WHERE id=?", (d["sig"], it.local_id))
            elif it.status == "dup" and not it.include:
                con.execute("UPDATE recurring SET mm_uid=?, mm_sig=? WHERE id=? AND mm_uid IS NULL",
                            (it.key, d["sig"], it.local_id))
            elif it.include:
                con.execute("INSERT INTO recurring(description, type, account_id, to_account_id, category_id, "
                            "amount, currency, freq, day, next_date, end_date, mm_uid, mm_sig) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (*vals, d["freq"], d["day"], d["next_date"], d["end_date"], it.key, d["sig"]))
                n += 1
            else:
                ignore("recurring", it.key)
        stats["recurring"] = n

        # movimientos
        def plan(uid: Optional[str]) -> Optional[int]:
            if not uid:
                return None
            row = con.execute("SELECT id FROM plans WHERE mm_uid=?", (uid,)).fetchone()
            if row:
                return row["id"]
            p = an.plans[uid]
            return con.execute("INSERT INTO plans(description, account_id, category_id, total, n, first_date, "
                               "mm_uid) VALUES(?,?,?,?,?,?,?)",
                               (p["description"], acc(p["account"]), cat(p["ctg"]), p["total"], p["n"],
                                p["first"].isoformat(), uid)).lastrowid

        n = upd = 0
        for it in by_kind("txn"):
            d = it.data
            f = dict(account_id=acc(d["account"]), to_account_id=acc(d["to_account"]), category_id=cat(d["ctg"]),
                     type=d["type"], amount=d["amount"], description=d["description"], note=d["note"],
                     date=d["date"], time=d["time"], orig_amount=d["orig_amount"],
                     orig_currency=d["orig_currency"], to_amount=d["to_amount"], adjust=d["adjust"])
            if it.status == "changed":
                if it.include:
                    sets = ", ".join(f"{k}=?" for k in f)
                    con.execute(f"UPDATE transactions SET {sets} WHERE id=?", (*f.values(), it.local_id))
                    upd += 1
                con.execute("UPDATE transactions SET mm_sig=? WHERE id=?", (d["sig"], it.local_id))
            elif it.status == "dup" and not it.include:
                con.execute("UPDATE transactions SET mm_uid=?, mm_sig=? WHERE id=? AND mm_uid IS NULL",
                            (it.key, d["sig"], it.local_id))
            elif it.include:
                db.add_txn(**f, plan_id=plan(d["plan"]), inst_no=d["inst_no"], mm_uid=it.key, mm_sig=d["sig"])
                n += 1
            else:
                ignore("txn", it.key)
        stats["transactions"], stats["updated"] = n, upd

        # comisiones → su transferencia (comparten txUidFee en la app)
        fee_tx = {i.data["fee_key"]: i.key for i in by_kind("txn")
                  if i.data["fee_key"] and i.data["type"] == "transfer"}
        for it in by_kind("txn"):
            if it.data["fee_key"] and it.data["type"] != "transfer" and it.data["fee_key"] in fee_tx:
                con.execute("""UPDATE transactions SET fee_of=(SELECT id FROM transactions WHERE mm_uid=?)
                               WHERE mm_uid=? AND fee_of IS NULL""", (fee_tx[it.data["fee_key"]], it.key))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return stats


# ════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════
def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    path = Path(argv[0]).expanduser()
    db = Database()
    an = analyze(path, db)
    print(f"{path}  →  {db.path}")
    print(f"new {an.count('new')} · possible duplicates {an.count('dup')} · changed in the app "
          f"{an.count('changed')} · already imported {sum(an.same.values())} · ignored before {an.ignored}")
    for it in an.items:
        amt = f"{it.amount:>14,.2f} {it.currency}" if it.amount is not None else ""
        mark = "x" if it.include else " "
        print(f"[{mark}] {it.status:7} {it.kind:9} {it.date:10} {it.label[:44]:44} {it.account[:30]:30} {amt}"
              + (f"  ({it.detail})" if it.detail else ""))
    for s in an.skipped:
        print(f"skipped: {s}")
    if "--apply" in argv:
        print(apply(an, db))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
