"""
expenses_rates.py — cotizaciones de internet para el gestor de gastos
════════════════════════════════════════════════════════════════
Gratis y sin clave. Valor = cuántas unidades de la moneda principal
(expenses_db.MAIN_CURRENCY) vale 1 unidad de la otra.

  market   https://open.er-api.com/v6/latest/<principal> — cualquier par,
           se actualiza una vez por día (una sola consulta para todas)
  si la principal es ARS, además DolarAPI (https://dolarapi.com, venta):
    USD    /v1/dolares/<casa>   oficial, bolsa (MEP), blue, contadoconliqui,
                                mayorista, cripto, tarjeta
    otras  /v1/cotizaciones/<código>  (oficial: EUR, BRL, CLP, UYU)
  manual   no se actualiza

La fuente de cada moneda va en currencies.source ('' = default_source()).
expenses_tui.py las pide al abrirse, en un hilo aparte (fetch_all no toca la base).
════════════════════════════════════════════════════════════════
"""

import json
import urllib.request
from datetime import datetime
from typing import Optional

from expenses_db import MAIN_CURRENCY

MARKET_API = "https://open.er-api.com/v6/latest"
DOLAR_API = "https://dolarapi.com/v1"
DOLAR_SOURCES = [("oficial", "official"), ("bolsa", "MEP"), ("blue", "blue"), ("contadoconliqui", "CCL"),
                 ("mayorista", "wholesale"), ("cripto", "crypto"), ("tarjeta", "card (with taxes)")]
TIMEOUT = 5.0


def default_source(code: str) -> str:
    if MAIN_CURRENCY == "ARS" and code in ("USD", "EUR", "BRL", "CLP", "UYU"):
        return "oficial"
    return "market"


def effective_source(code: str, source: str) -> str:
    return source or default_source(code)


def source_label(source: str) -> str:
    if source in ("manual", "market"):
        return "manual" if source == "manual" else "market (open.er-api.com)"
    return f"DolarAPI · {dict(DOLAR_SOURCES).get(source, source)}"


def source_choices(code: str) -> list[tuple[str, str]]:
    """Opciones del selector de fuente para una moneda."""
    out = [(source_label("market"), "market")]
    if MAIN_CURRENCY == "ARS":
        out += [(source_label(k), k) for k, _ in (DOLAR_SOURCES if code == "USD" else DOLAR_SOURCES[:1])]
    return out + [("manual (fixed rate)", "manual")]


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "expenses-tui"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def _local(when: str) -> str:
    try:
        return datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        try:   # formato RFC 2822 de open.er-api.com
            return datetime.strptime(when, "%a, %d %b %Y %H:%M:%S %z").astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return when


def fetch_dolar(code: str, source: str) -> tuple[float, str]:
    d = _get(f"{DOLAR_API}/dolares/{source}" if code == "USD" else f"{DOLAR_API}/cotizaciones/{code.lower()}")
    rate = float(d["venta"])
    if rate <= 0:
        raise ValueError("rate is 0")
    return rate, _local(d.get("fechaActualizacion", ""))


def fetch_all(pairs: list[tuple[str, str]]) -> dict[str, tuple[Optional[float], str]]:
    """{código: (cotización, fecha) o (None, error)} para [(código, fuente)]."""
    out: dict[str, tuple[Optional[float], str]] = {}
    market = [c for c, s in pairs if s == "market"]
    if market:
        try:
            d = _get(f"{MARKET_API}/{MAIN_CURRENCY}")
            if d.get("result") != "success":
                raise ValueError(d.get("error-type", "bad response"))
            when = _local(d.get("time_last_update_utc", ""))
            for c in market:
                per_main = float(d["rates"].get(c) or 0)
                out[c] = (round(1 / per_main, 6), when) if per_main > 0 else (None, "unknown currency")
        except Exception as e:  # noqa: BLE001 - sin red, timeout, respuesta rara
            for c in market:
                out[c] = (None, str(getattr(e, "reason", e)))
    for code, source in pairs:
        if source != "market":
            try:
                out[code] = fetch_dolar(code, source)
            except Exception as e:  # noqa: BLE001
                out[code] = (None, str(getattr(e, "reason", e)))
    return out
