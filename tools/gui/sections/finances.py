"""Finances (Settings): gestión de cuentas, categorías, cotizaciones, import y export — lo mismo que
FinancesView de la TUI. La lógica y los formularios son los de sections/expenses.py; el uso diario
(movimientos, cuotas, fijos, tarjetas) está en la GUI de Gastos (Mod+G), que se abre desde acá."""

from __future__ import annotations

from . import _lib as L
from . import expenses as GX

UI: dict = {}


def get() -> dict:
    with GX.LOCK:
        try:
            s = GX.db().summary()
            cur = s.get("currency", "")
            over = [L.info("net", "Net worth", GX.money(s["net"], cur)), L.info("inc", "Income this month", GX.money(s["income"])),
                    L.info("exp", "Expenses this month", GX.money(s["expenses"])),
                    L.info("bud", "Budget used", f"{GX.money(s['budget_spent'])} / {GX.money(s['budget'])}"),
                    L.button("open", "Expenses", "Transactions, installments, recurring and cards (Mod+G)", "Open")]
            groups = [L.group("Overview", over)] + GX.manage_groups()
        except Exception as e:  # noqa: BLE001
            return L.page("Finances", f"Database unavailable: {e}"[:100], [])
    return L.page("Finances", GX.STATE["rates"] or "Accounts, categories, exchange rates, import and export", groups, refresh=30)


def set_value(key, value):
    return L.fail("Unknown field")


def act(key: str, text=None):
    if key == "open":
        L.detach(["bash", str(L.Path.home() / ".config/waybar/scripts/expenses-launch.sh")])  # en modo gui abre la GUI de Gastos
        return {"ok": True, "msg": "", "close": True}
    return GX.act(key, text)
