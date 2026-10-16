"""
expenses_db.py — base de datos del gestor de gastos (SQLite, sin dependencias)
════════════════════════════════════════════════════════════════
db     : ~/.local/state/dotfiles/expenses/expenses.db  (o $EXPENSES_DB)
moneda : EXPENSES_CURRENCY de ~/.config/dotfiles/user.conf; si no, la del
         locale del sistema (LC_MONETARY); si no, USD. Las que se cotizan de
         internet: EXPENSES_RATES (por defecto USD,EUR), ver expenses_rates.py.

La usan la TUI (expenses_tui.py), el importador de Money Manager
(expenses_import.py) y el widget Money de config/desktop-widgets.

Modelo (lo mismo que guarda Money Manager):
  accounts      cuentas; las tarjetas llevan día de cierre/pago y la cuenta
                desde la que se pagan
  categories    de gasto o de ingreso, con presupuesto mensual por defecto
  budgets       presupuesto de una categoría para un mes puntual (pisa el default)
  currencies    cotización de cada moneda contra la principal (= 1); source = de
                dónde se actualiza (expenses_rates.py, al abrir la TUI) o manual
  transactions  gasto / ingreso / transferencia. `amount` va en la moneda de
                la cuenta; si se pagó en otra moneda queda en orig_amount /
                orig_currency. adjust = ajuste de saldo ("Modificar saldo").
                Las cuotas apuntan a su plan (plan_id, inst_no) y las
                comisiones a su transferencia (fee_of).
  plans         compras en cuotas: las cuotas se crean de una como
                transacciones con fecha futura (igual que la app)
  recurring     gastos/ingresos fijos que se generan solos al llegar la fecha
  mm_uid        en cada tabla: de qué registro de Money Manager vino (para
                que un import nuevo solo agregue lo que no está); mm_sig, cómo
                estaba en la app al importarlo (para ver si cambió allá)
  mm_ignored    lo que se desmarcó en un import: no se vuelve a ofrecer
════════════════════════════════════════════════════════════════
"""

import calendar
import locale
import os
import shlex
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
DB_FILE = Path(os.environ.get("EXPENSES_DB") or STATE_HOME / "dotfiles" / "expenses" / "expenses.db")
SCHEMA_VERSION = 1


def _user_conf() -> dict[str, str]:
    """KEY=VALUE de ~/.config/dotfiles/user.conf (sintaxis de shell, sin ejecutarlo)."""
    out = {}
    try:
        for line in (CONFIG_HOME / "dotfiles" / "user.conf").read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                try:
                    out[k.strip()] = " ".join(shlex.split(v, comments=True))
                except ValueError:
                    out[k.strip()] = v.strip().strip("\"'")
    except OSError:
        pass
    return out


def _locale_currency() -> str:
    """Código ISO de la moneda del locale (LC_MONETARY), o vacío."""
    try:
        locale.setlocale(locale.LC_MONETARY, "")
        code = locale.localeconv().get("int_curr_symbol", "").strip()
        return code if len(code) == 3 and code.isalpha() else ""
    except (locale.Error, ValueError):
        return ""


_CONF = _user_conf()
MAIN_CURRENCY = (os.environ.get("EXPENSES_CURRENCY") or _CONF.get("EXPENSES_CURRENCY") or _locale_currency()
                 or "USD").upper()

# (clave, etiqueta, icono). Los grupos de Money Manager se mapean a estos en expenses_import.py.
ACCT_TYPES = [
    ("cash", "cash", "💵"), ("bank", "bank account", "🏦"), ("card", "credit card", "💳"),
    ("debit", "debit card", "💳"), ("savings", "savings", "🐷"), ("investments", "investments", "📈"),
    ("prepaid", "prepaid / wallet", "👛"), ("loan", "loan", "🧾"), ("crypto", "crypto", "₿"),
    ("other", "other", "◻"),
]
ACCT_ICONS = {k: i for k, _, i in ACCT_TYPES} | {"wallet": "👛"}   # wallet: tipo de la versión 1
TXN_TYPES = ["expense", "income", "transfer"]
FREQS = ["monthly", "weekly", "yearly", "daily"]


# ════════════════════════════════════════════════════════════════
#  FECHAS
# ════════════════════════════════════════════════════════════════
def add_months(d: date, n: int, day: Optional[int] = None) -> date:
    """d + n meses, con el día `day` (o el de d) recortado al largo del mes."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(day or d.day, calendar.monthrange(y, m)[1]))


def next_date(d: date, freq: str, day: int) -> date:
    if freq == "daily":
        return date.fromordinal(d.toordinal() + 1)
    if freq == "weekly":
        return date.fromordinal(d.toordinal() + 7)
    return add_months(d, 12 if freq == "yearly" else 1, day)


def card_cycle(close_day: int, pay_day: int, today: date) -> dict:
    """Ciclo de una tarjeta: último cierre, el anterior, el próximo y los
    vencimientos de cada resumen (el vencimiento cae después del cierre)."""
    last = add_months(today, 0 if today.day > close_day else -1, close_day)
    prev, nxt = add_months(last, -1, close_day), add_months(last, 1, close_day)

    def due(close: date) -> date:
        return add_months(close, 0 if pay_day > close_day else 1, pay_day)

    return {"prev_close": prev, "last_close": last, "next_close": nxt,
            "last_due": due(last), "next_due": due(nxt)}


def split_installments(total: float, n: int) -> list[float]:
    """Monto de cada cuota; el redondeo va a la primera (como Money Manager:
    27333.35 + 5 × 27333.33)."""
    each = round(total / n, 2)
    return [round(total - each * (n - 1), 2)] + [each] * (n - 1)


# ════════════════════════════════════════════════════════════════
#  BASE
# ════════════════════════════════════════════════════════════════
SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL UNIQUE,
    type           TEXT    NOT NULL DEFAULT 'other',
    init_bal       REAL    NOT NULL DEFAULT 0,
    currency       TEXT    NOT NULL DEFAULT '',
    notes          TEXT    NOT NULL DEFAULT '',
    created        TEXT    DEFAULT (date('now'))
);
CREATE TABLE IF NOT EXISTS categories (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT    NOT NULL,
    kind      TEXT    NOT NULL DEFAULT 'expense',
    icon      TEXT    NOT NULL DEFAULT '◻',
    budget    REAL    NOT NULL DEFAULT 0,
    parent_id INTEGER REFERENCES categories(id) ON DELETE CASCADE,
    sort      INTEGER NOT NULL DEFAULT 0,
    mm_uid    TEXT,
    created   TEXT    DEFAULT (date('now')),
    UNIQUE(name, kind)
);
CREATE TABLE IF NOT EXISTS budgets (
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    month       TEXT    NOT NULL,
    amount      REAL    NOT NULL,
    PRIMARY KEY (category_id, month)
);
CREATE TABLE IF NOT EXISTS mm_ignored (
    kind   TEXT NOT NULL,
    mm_uid TEXT NOT NULL,
    PRIMARY KEY (kind, mm_uid)
);
CREATE TABLE IF NOT EXISTS currencies (
    code TEXT PRIMARY KEY,
    rate REAL NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    description TEXT    NOT NULL,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    category_id INTEGER          REFERENCES categories(id) ON DELETE SET NULL,
    total       REAL    NOT NULL,
    n           INTEGER NOT NULL,
    first_date  TEXT    NOT NULL,
    mm_uid      TEXT,
    created     TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS recurring (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    description   TEXT    NOT NULL,
    type          TEXT    NOT NULL DEFAULT 'expense',
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    to_account_id INTEGER          REFERENCES accounts(id) ON DELETE SET NULL,
    category_id   INTEGER          REFERENCES categories(id) ON DELETE SET NULL,
    amount        REAL    NOT NULL,
    currency      TEXT    NOT NULL DEFAULT '',
    freq          TEXT    NOT NULL DEFAULT 'monthly',
    day           INTEGER NOT NULL DEFAULT 1,
    next_date     TEXT    NOT NULL,
    end_date      TEXT    NOT NULL DEFAULT '',
    active        INTEGER NOT NULL DEFAULT 1,
    mm_uid        TEXT,
    created       TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id)    ON DELETE CASCADE,
    to_account_id INTEGER          REFERENCES accounts(id)    ON DELETE SET NULL,
    category_id   INTEGER          REFERENCES categories(id)  ON DELETE SET NULL,
    type          TEXT    NOT NULL,
    amount        REAL    NOT NULL,
    description   TEXT    NOT NULL,
    note          TEXT    NOT NULL DEFAULT '',
    date          TEXT    NOT NULL,
    created       TEXT    DEFAULT (datetime('now'))
);
"""

# Columnas que se suman con ALTER TABLE (una base de una versión anterior se
# completa sola al abrirla)
COLUMNS = {
    "accounts": [
        ("close_day", "INTEGER NOT NULL DEFAULT 0"),      # tarjeta: día de cierre (0 = no es tarjeta)
        ("pay_day", "INTEGER NOT NULL DEFAULT 0"),        # tarjeta: día de vencimiento
        ("pay_account_id", "INTEGER REFERENCES accounts(id) ON DELETE SET NULL"),
        ("hidden", "INTEGER NOT NULL DEFAULT 0"),
        ("sort", "INTEGER NOT NULL DEFAULT 0"),
        ("mm_uid", "TEXT"),
    ],
    "transactions": [
        ("time", "TEXT NOT NULL DEFAULT ''"),
        ("orig_amount", "REAL"),                          # monto en la moneda en que se pagó
        ("orig_currency", "TEXT NOT NULL DEFAULT ''"),
        ("to_amount", "REAL"),                            # transferencia entre monedas: lo que entra
        ("adjust", "INTEGER NOT NULL DEFAULT 0"),         # ajuste de saldo
        ("plan_id", "INTEGER REFERENCES plans(id) ON DELETE CASCADE"),
        ("inst_no", "INTEGER"),
        ("fee_of", "INTEGER REFERENCES transactions(id) ON DELETE CASCADE"),
        ("recurring_id", "INTEGER REFERENCES recurring(id) ON DELETE SET NULL"),
        ("mm_uid", "TEXT"),
        ("mm_sig", "TEXT"),                               # cómo estaba en la app al importarlo
    ],
    "recurring": [
        ("mm_sig", "TEXT"),
    ],
    "currencies": [
        ("source", "TEXT NOT NULL DEFAULT ''"),           # '' = la de expenses_rates.default_source; 'manual'; o una fuente
        ("updated", "TEXT NOT NULL DEFAULT ''"),          # fecha de la cotización
    ],
}
# Siempre presentes y cotizadas de internet (EXPENSES_RATES de user.conf), menos la principal
AUTO_CURRENCIES = tuple(c for c in (x.strip().upper() for x in _CONF.get("EXPENSES_RATES", "USD,EUR").split(","))
                        if len(c) == 3 and c.isalpha() and c != MAIN_CURRENCY)

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_t_date ON transactions(date DESC);
CREATE INDEX IF NOT EXISTS idx_t_acc  ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_t_plan ON transactions(plan_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_acc_mm  ON accounts(mm_uid);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cat_mm  ON categories(mm_uid);
CREATE UNIQUE INDEX IF NOT EXISTS ux_plan_mm ON plans(mm_uid);
CREATE UNIQUE INDEX IF NOT EXISTS ux_rec_mm  ON recurring(mm_uid);
CREATE UNIQUE INDEX IF NOT EXISTS ux_txn_mm  ON transactions(mm_uid);
"""


class Database:
    def __init__(self, path: Path = DB_FILE):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(path), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self._migrate()
        self.con.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def readonly(cls, path: Path = DB_FILE) -> "Database":
        """Abierta en solo lectura y sin migrar (para el widget de escritorio)."""
        self = cls.__new__(cls)
        self.path = path
        self.con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        return self

    def _cols(self, table: str) -> set[str]:
        return {r["name"] for r in self.con.execute(f"PRAGMA table_info({table})")}

    def _migrate(self) -> None:
        self.con.execute("PRAGMA foreign_keys = OFF")
        self.con.executescript(SCHEMA)
        for table, cols in COLUMNS.items():
            have = self._cols(table)
            for name, decl in cols:
                if name not in have:
                    self.con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
        self.con.executescript(INDEXES)
        self.con.execute("INSERT OR IGNORE INTO currencies(code, rate, source) VALUES(?, 1, 'manual')",
                         (MAIN_CURRENCY,))
        for code in AUTO_CURRENCIES:                     # sin cotización (0) hasta la primera consulta
            self.con.execute("INSERT OR IGNORE INTO currencies(code, rate) VALUES(?, 0)", (code,))
        self.con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.con.commit()

    # ── consultas ──

    def q(self, sql: str, p: tuple = ()) -> list:
        return self.con.execute(sql, p).fetchall()

    def q1(self, sql: str, p: tuple = ()):
        return self.con.execute(sql, p).fetchone()

    def val(self, sql: str, p: tuple = (), default=0):
        row = self.con.execute(sql, p).fetchone()
        return row[0] if row and row[0] is not None else default

    def run(self, sql: str, p: tuple = ()) -> int:
        cur = self.con.execute(sql, p)
        self.con.commit()
        return cur.lastrowid

    def backup(self) -> Path:
        """Copia de la base al lado (expenses.db.bak-AAAAMMDD-HHMMSS) antes de un import."""
        dst = self.path.with_name(f"{self.path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        out = sqlite3.connect(str(dst))
        with out:
            self.con.backup(out)
        out.close()
        return dst

    # ── monedas ──

    def rate(self, code: str) -> float:
        return float(self.val("SELECT rate FROM currencies WHERE code=?", (code,), 0) or 0)

    def convert(self, amount: float, frm: str, to: str) -> Optional[float]:
        """amount de `frm` a `to` usando las cotizaciones (None si falta alguna)."""
        if frm == to or not frm:
            return amount
        a, b = self.rate(frm), self.rate(to)
        return round(amount * a / b, 2) if a and b else None

    # ── saldos ──

    def balances(self, upto: Optional[str] = None) -> dict[int, float]:
        """Saldo de cada cuenta contando los movimientos hasta `upto` (hoy por
        defecto): las cuotas y fijos con fecha futura todavía no cuentan."""
        upto = upto or date.today().isoformat()
        out = {r["id"]: float(r["init_bal"]) for r in self.q("SELECT id, init_bal FROM accounts")}
        for r in self.q("""
                SELECT account_id, to_account_id, type, amount, to_amount
                FROM transactions WHERE date <= ?""", (upto,)):
            if r["type"] == "income":
                out[r["account_id"]] = out.get(r["account_id"], 0) + r["amount"]
            else:
                out[r["account_id"]] = out.get(r["account_id"], 0) - r["amount"]
                if r["type"] == "transfer" and r["to_account_id"]:
                    inc = r["to_amount"] if r["to_amount"] is not None else r["amount"]
                    out[r["to_account_id"]] = out.get(r["to_account_id"], 0) + inc
        return out

    # ── ajustes ──

    def adjust(self, acc_id: int, diff: float, when: Optional[str] = None,
               description: str = "Balance adjustment", note: str = "") -> Optional[int]:
        """Ajuste de saldo (como "Modificar saldo" de la app): + suma, − resta."""
        if abs(diff) < 0.005:
            return None
        tid = self.add_txn(account_id=acc_id, type="income" if diff > 0 else "expense", amount=round(abs(diff), 2),
                           description=description, note=note, date=when or date.today().isoformat(), adjust=1)
        self.con.commit()
        return tid

    def set_balance(self, acc_id: int, target: float, note: str = "") -> Optional[int]:
        """Lleva el saldo de hoy de la cuenta a `target` con un ajuste por la diferencia."""
        return self.adjust(acc_id, target - self.balances().get(acc_id, 0.0), note=note)

    def card_spent(self, acc_id: int, lo: date, hi: date) -> float:
        """Consumos de una tarjeta en (lo, hi]: gastos menos devoluciones y ajustes a favor."""
        return float(self.val("""SELECT SUM(CASE type WHEN 'expense' THEN amount WHEN 'income' THEN -amount END)
                                 FROM transactions WHERE account_id=? AND type<>'transfer' AND date > ? AND date <= ?""",
                              (acc_id, lo.isoformat(), hi.isoformat())))

    def card_status(self, a, today: Optional[date] = None) -> Optional[dict]:
        """Estado de una tarjeta (fila de accounts): ciclo, resumen cerrado,
        pagado desde el cierre, ciclo en curso y cuotas de después."""
        if not a["close_day"]:
            return None
        today = today or date.today()
        cy = card_cycle(a["close_day"], a["pay_day"] or a["close_day"], today)
        paid = self.val("SELECT SUM(COALESCE(to_amount, amount)) FROM transactions WHERE to_account_id=? "
                        "AND type='transfer' AND date > ? AND date <= ?",
                        (a["id"], cy["last_close"].isoformat(), today.isoformat()))
        return cy | {"closed": self.card_spent(a["id"], cy["prev_close"], cy["last_close"]), "paid": float(paid),
                     "current": self.card_spent(a["id"], cy["last_close"], cy["next_close"]),
                     "upcoming": float(self.val("SELECT SUM(amount) FROM transactions WHERE account_id=? AND "
                                                "plan_id IS NOT NULL AND date > ?",
                                                (a["id"], cy["next_close"].isoformat())))}

    def summary(self, today: Optional[date] = None) -> dict:
        """Balance general (widget Money): patrimonio, mes en curso,
        presupuesto y tarjetas. Las cuentas ocultas no cuentan."""
        today = today or date.today()
        ym = today.strftime("%Y-%m")
        bal = self.balances()
        accs = self.q("SELECT * FROM accounts WHERE hidden=0 ORDER BY sort, name")
        conv = {a["id"]: self.convert(bal.get(a["id"], 0.0), a["currency"], MAIN_CURRENCY) or 0.0 for a in accs}
        month = {r["type"]: float(r["s"]) for r in self.q(
            "SELECT type, SUM(amount) AS s FROM transactions WHERE adjust=0 AND type IN ('income','expense') "
            "AND date LIKE ? AND date <= ? GROUP BY type", (ym + "%", today.isoformat()))}
        spent = budget = 0.0
        for c in self.q("SELECT id FROM categories WHERE kind='expense'"):
            if (b := self.budget_for(c["id"], ym)) > 0:
                budget += b
                spent += float(self.val("SELECT SUM(amount) FROM transactions WHERE category_id=? AND adjust=0 "
                                        "AND type='expense' AND date LIKE ?", (c["id"], ym + "%")))
        cards = []
        for a in accs:
            if a["type"] == "card" and (st := self.card_status(a, today)):
                cards.append({"name": a["name"], "debt": -bal.get(a["id"], 0.0), "due": st["next_due"].isoformat(),
                              "closed_left": max(0.0, st["closed"] - st["paid"]), "last_due": st["last_due"].isoformat(),
                              "current": st["current"]})
        return {"currency": MAIN_CURRENCY, "net": sum(conv.values()),
                "assets": sum(v for a in accs if a["type"] != "card" and (v := conv[a["id"]]) > 0),
                "debt": -sum(v for v in conv.values() if v < 0),
                "income": month.get("income", 0.0), "expenses": month.get("expense", 0.0),
                "budget": budget, "budget_spent": spent, "cards": cards,
                "rates": {r["code"]: r["rate"] for r in self.q("SELECT code, rate FROM currencies WHERE code<>?",
                                                               (MAIN_CURRENCY,))}}

    def budget_for(self, cat_id: int, month: str) -> float:
        """Presupuesto de la categoría en el mes (el del mes o, si no hay, el default)."""
        row = self.q1("SELECT amount FROM budgets WHERE category_id=? AND month=?", (cat_id, month))
        return float(row["amount"]) if row else float(self.val("SELECT budget FROM categories WHERE id=?",
                                                               (cat_id,)))

    # ── altas compuestas ──

    def add_txn(self, **f) -> int:
        cols = ", ".join(f)
        cur = self.con.execute(f"INSERT INTO transactions({cols}) VALUES({', '.join('?' * len(f))})",
                               tuple(f.values()))
        return cur.lastrowid

    def create_plan(self, description: str, account_id: int, category_id: Optional[int], total: float,
                    n: int, first: date, note: str = "", mm_uid: Optional[str] = None) -> int:
        """Compra en cuotas: el plan + una transacción por cuota, una por mes."""
        pid = self.con.execute(
            "INSERT INTO plans(description, account_id, category_id, total, n, first_date, mm_uid) "
            "VALUES(?,?,?,?,?,?,?)",
            (description, account_id, category_id, total, n, first.isoformat(), mm_uid)).lastrowid
        for i, amount in enumerate(split_installments(total, n)):
            self.add_txn(account_id=account_id, category_id=category_id, type="expense", amount=amount,
                         description=description, note=note, date=add_months(first, i).isoformat(),
                         plan_id=pid, inst_no=i + 1)
        self.con.commit()
        return pid

    def post_recurring(self, today: Optional[date] = None) -> list[str]:
        """Genera las transacciones de los fijos que vencieron (hasta hoy) y
        corre su próxima fecha. Devuelve las descripciones generadas."""
        today = today or date.today()
        done = []
        for r in self.q("SELECT * FROM recurring WHERE active=1 AND next_date <= ?", (today.isoformat(),)):
            acc = self.q1("SELECT currency FROM accounts WHERE id=?", (r["account_id"],))
            if not acc:
                continue
            d = date.fromisoformat(r["next_date"])
            end = date.fromisoformat(r["end_date"]) if r["end_date"] else None
            while d <= today and (end is None or d <= end):
                cur = r["currency"] or acc["currency"]
                amount = self.convert(r["amount"], cur, acc["currency"])
                f = dict(account_id=r["account_id"], category_id=r["category_id"], type=r["type"],
                         description=r["description"], date=d.isoformat(), recurring_id=r["id"],
                         amount=amount if amount is not None else r["amount"])
                if cur != acc["currency"]:
                    f |= dict(orig_amount=r["amount"], orig_currency=cur)
                if r["type"] == "transfer":
                    f["to_account_id"] = r["to_account_id"]
                self.add_txn(**f)
                done.append(f"{r['description']} {d:%d/%m}")
                d = next_date(d, r["freq"], r["day"])
            self.con.execute("UPDATE recurring SET next_date=?, active=? WHERE id=?",
                             (d.isoformat(), 0 if end and d > end else 1, r["id"]))
        self.con.commit()
        return done

    # ── export ──

    def export_csv(self) -> str:
        def c(v) -> str:
            return '"' + str(v if v is not None else "").replace('"', '""') + '"'

        lines = ["id,date,type,description,account,to_account,category,amount,currency,"
                 "orig_amount,orig_currency,installment,adjust,note"]
        for r in self.q("""
                SELECT tx.*, a.name AS aname, a.currency, COALESCE(c.name,'') AS cname,
                       COALESCE(ta.name,'') AS taname, p.n AS pn
                FROM transactions tx
                JOIN accounts a ON a.id = tx.account_id
                LEFT JOIN categories c ON c.id = tx.category_id
                LEFT JOIN accounts ta ON ta.id = tx.to_account_id
                LEFT JOIN plans p ON p.id = tx.plan_id
                ORDER BY tx.date DESC, tx.id DESC"""):
            inst = f"{r['inst_no']}/{r['pn']}" if r["plan_id"] else ""
            lines.append(",".join([str(r["id"]), r["date"], r["type"], c(r["description"]), c(r["aname"]),
                                   c(r["taname"]), c(r["cname"]), str(r["amount"]), r["currency"],
                                   str(r["orig_amount"] or ""), r["orig_currency"], inst,
                                   str(r["adjust"]), c(r["note"])]))
        return "\n".join(lines)

