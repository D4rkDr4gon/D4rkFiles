"""agenda.py — próximos eventos para el widget Agenda (sin dependencias).

Dos fuentes, según `agenda_source` en la config de los widgets:
- `obsidian`: los calendarios del plugin Full Calendar de un vault
  (`agenda_vault`): lee .obsidian/plugins/obsidian-full-calendar/data.json y
  usa todos sus calendarios con sus colores — los `local` (una nota por
  evento, con frontmatter `date`/`startTime`/`endTime`/`allDay` o
  `type: recurring` + `daysOfWeek`/`startRecur`/`endRecur`) y los `ical`
  (URLs remotas). El vault solo se lee.
- `ics`: `agenda_ics`, URLs (http/https/webcal) o rutas a archivos .ics
  separadas por espacios.

Los .ics remotos se cachean (AGENDA_TTL) en el estado de los widgets; sin red
se usa la última copia. El parser cubre lo que generan Outlook, Proton y
Google: líneas plegadas, TZID (también los nombres de Windows de Outlook),
fechas UTC/flotantes/de día completo, RRULE DAILY/WEEKLY/MONTHLY/YEARLY con
INTERVAL, COUNT, UNTIL, BYDAY (con ordinal: 2TU, -1FR), BYMONTHDAY y
BYMONTH, EXDATE, excepciones por RECURRENCE-ID y STATUS:CANCELLED.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

AGENDA_TTL = 30 * 60
LOCAL_TZ = datetime.now().astimezone().tzinfo

# Nombres de zona de Windows (Outlook / Exchange) → IANA. Los más comunes;
# uno desconocido cae a la zona local.
WINDOWS_TZ = {
    "Argentina Standard Time": "America/Argentina/Buenos_Aires",
    "SA Eastern Standard Time": "America/Cayenne", "E. South America Standard Time": "America/Sao_Paulo",
    "Pacific SA Standard Time": "America/Santiago", "SA Pacific Standard Time": "America/Bogota",
    "SA Western Standard Time": "America/La_Paz", "Venezuela Standard Time": "America/Caracas",
    "Montevideo Standard Time": "America/Montevideo", "Paraguay Standard Time": "America/Asuncion",
    "Central Standard Time": "America/Chicago", "Central Standard Time (Mexico)": "America/Mexico_City",
    "Eastern Standard Time": "America/New_York", "Mountain Standard Time": "America/Denver",
    "Pacific Standard Time": "America/Los_Angeles", "US Mountain Standard Time": "America/Phoenix",
    "Alaskan Standard Time": "America/Anchorage", "Hawaiian Standard Time": "Pacific/Honolulu",
    "GMT Standard Time": "Europe/London", "Greenwich Standard Time": "Atlantic/Reykjavik",
    "W. Europe Standard Time": "Europe/Berlin", "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest", "Central European Standard Time": "Europe/Warsaw",
    "E. Europe Standard Time": "Europe/Chisinau", "FLE Standard Time": "Europe/Kiev",
    "GTB Standard Time": "Europe/Bucharest", "Russian Standard Time": "Europe/Moscow",
    "Israel Standard Time": "Asia/Jerusalem", "Arabian Standard Time": "Asia/Dubai",
    "India Standard Time": "Asia/Kolkata", "China Standard Time": "Asia/Shanghai",
    "Tokyo Standard Time": "Asia/Tokyo", "Singapore Standard Time": "Asia/Singapore",
    "AUS Eastern Standard Time": "Australia/Sydney", "New Zealand Standard Time": "Pacific/Auckland",
    "UTC": "UTC", "Coordinated Universal Time": "UTC",
}
WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
# Full Calendar: U M T W R F S
FC_DAYS = {"U": 6, "M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5}


def tz_for(name: str | None):
    if not name:
        return LOCAL_TZ
    name = name.strip('"')
    try:
        return ZoneInfo(WINDOWS_TZ.get(name, name))
    except (ZoneInfoNotFoundError, ValueError):
        return LOCAL_TZ


# ── ICS ───────────────────────────────────────────────────

def unfold(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def unescape(v: str) -> str:
    return v.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def parse_line(line: str) -> tuple[str, dict, str]:
    """`NAME;P1=a;P2=b:valor` → (NAME, {P1: a, P2: b}, valor)."""
    head, _, value = line.partition(":")
    # Un ':' dentro de un parámetro entre comillas (raro) no se contempla
    name, *params = head.split(";")
    return name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value


def parse_dt(value: str, params: dict) -> tuple[datetime, bool]:
    """(datetime con zona, es_día_completo)."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        d = datetime.strptime(value[:8], "%Y%m%d")
        return d.replace(tzinfo=LOCAL_TZ), True
    if value.endswith("Z"):
        return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc), False
    return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").replace(tzinfo=tz_for(params.get("TZID"))), False


def parse_duration(v: str) -> timedelta:
    m = re.fullmatch(r"([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", v.strip())
    if not m:
        return timedelta(0)
    sign, w, d, h, mi, s = m.groups()
    td = timedelta(weeks=int(w or 0), days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0), seconds=int(s or 0))
    return -td if sign == "-" else td


def parse_ics(text: str) -> list[dict]:
    """VEVENTs crudos: {uid, summary, start, end, allday, rrule, exdates, rid, cancelled}."""
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {"exdates": set(), "rrule": None, "rid": None, "end": None, "dur": None, "cancelled": False}
            continue
        if line == "END:VEVENT":
            if cur and cur.get("start"):
                if cur["end"] is None:
                    cur["end"] = cur["start"] + (cur["dur"] or (timedelta(days=1) if cur["allday"] else timedelta(0)))
                events.append(cur)
            cur = None
            continue
        if cur is None:
            continue
        name, params, value = parse_line(line)
        if name == "UID":
            cur["uid"] = value
        elif name == "SUMMARY":
            cur["summary"] = unescape(value)
        elif name == "DTSTART":
            cur["start"], cur["allday"] = parse_dt(value, params)
        elif name == "DTEND":
            cur["end"], _ = parse_dt(value, params)
        elif name == "DURATION":
            cur["dur"] = parse_duration(value)
        elif name == "RRULE":
            cur["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
        elif name == "EXDATE":
            for v in value.split(","):
                cur["exdates"].add(parse_dt(v, params)[0])
        elif name == "RECURRENCE-ID":
            cur["rid"], _ = parse_dt(value, params)
        elif name == "STATUS":
            cur["cancelled"] = value.strip().upper() == "CANCELLED"
    return events


def _byday(rule: dict) -> list[tuple[int | None, int]]:
    out = []
    for item in filter(None, rule.get("BYDAY", "").split(",")):
        m = re.fullmatch(r"([+-]?\d+)?(MO|TU|WE|TH|FR|SA|SU)", item.strip())
        if m:
            out.append((int(m.group(1)) if m.group(1) else None, WEEKDAYS[m.group(2)]))
    return out


def _month_days(year: int, month: int, byday, bymonthday, default_day: int) -> list[int]:
    """Días del mes que cumplen BYDAY (con o sin ordinal) / BYMONTHDAY."""
    last = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)).day
    days = set()
    for n, wd in byday:
        matches = [d for d in range(1, last + 1) if date(year, month, d).weekday() == wd]
        if n is None:
            days.update(matches)
        elif -len(matches) <= n <= len(matches) and n != 0:
            days.add(matches[n - 1] if n > 0 else matches[n])
    for md in bymonthday:
        d = md if md > 0 else last + 1 + md
        if 1 <= d <= last:
            days.add(d)
    if not byday and not bymonthday:
        if default_day <= last:
            days.add(default_day)
    return sorted(days)


def expand(ev: dict, win_start: datetime, win_end: datetime, max_iter: int = 3000) -> list[datetime]:
    """Inicios de las ocurrencias de un evento que caen (o se pisan) con la ventana."""
    start, dur = ev["start"], ev["end"] - ev["start"]
    rule = ev.get("rrule")
    if not rule:
        return [start] if start < win_end and start + max(dur, timedelta(minutes=1)) > win_start else []
    freq = rule.get("FREQ", "").upper()
    interval = max(1, int(rule.get("INTERVAL", "1") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        until, _ = parse_dt(rule["UNTIL"], {})
        if len(rule["UNTIL"].strip()) == 8:            # UNTIL de día: incluye todo ese día
            until = until.replace(hour=23, minute=59, second=59)
    byday = _byday(rule)
    bymonthday = [int(x) for x in rule.get("BYMONTHDAY", "").split(",") if x.strip().lstrip("-").isdigit()]
    bymonth = [int(x) for x in rule.get("BYMONTH", "").split(",") if x.strip().isdigit()] or [start.month]
    tz, t0 = start.tzinfo, start.timetz().replace(tzinfo=None)

    def at(d: date) -> datetime:
        return datetime.combine(d, t0).replace(tzinfo=tz)

    out, n, i = [], 0, 0
    while i < max_iter:
        if freq == "DAILY":
            cands = [at(start.date() + timedelta(days=i * interval))]
        elif freq == "WEEKLY":
            week0 = start.date() - timedelta(days=start.weekday()) + timedelta(weeks=i * interval)
            wds = sorted({wd for _, wd in byday}) or [start.weekday()]
            cands = [at(week0 + timedelta(days=wd)) for wd in wds]
        elif freq == "MONTHLY":
            m = start.month - 1 + i * interval
            y, mo = start.year + m // 12, m % 12 + 1
            cands = [at(date(y, mo, d)) for d in _month_days(y, mo, byday, bymonthday, start.day)]
        elif freq == "YEARLY":
            y = start.year + i * interval
            cands = []
            for mo in bymonth:
                if byday or bymonthday:
                    cands += [at(date(y, mo, d)) for d in _month_days(y, mo, byday, bymonthday, start.day)]
                elif start.day <= 28 or mo != 2:
                    cands.append(at(date(y, mo, start.day)))
        else:
            break
        i += 1
        if not cands:
            continue
        for c in sorted(cands):
            if c < start:
                continue
            if (until and c > until) or (count is not None and n >= count) or c >= win_end:
                return out
            n += 1
            if c + max(dur, timedelta(minutes=1)) > win_start and c not in ev["exdates"]:
                out.append(c)
    return out


def ics_occurrences(text: str, win_start: datetime, win_end: datetime) -> list[dict]:
    raw = parse_ics(text)
    overrides = {(e.get("uid"), e["rid"]): e for e in raw if e["rid"] is not None}
    out = []
    for ev in raw:
        if ev["rid"] is not None:
            continue
        for s in expand(ev, win_start, win_end):
            o = overrides.get((ev.get("uid"), s))
            if o is not None:                          # excepción: se usa la versión editada
                if o["cancelled"]:
                    continue
                if not ev.get("cancelled"):
                    out.append(_occ(o, o["start"], o["end"] - o["start"]))
                continue
            if not ev["cancelled"]:
                out.append(_occ(ev, s, ev["end"] - ev["start"]))
    # Excepciones movidas a la ventana desde una ocurrencia que cae afuera
    seen = {(o["uid"], o["start"]) for o in out}
    for (uid, _rid), o in overrides.items():
        if not o["cancelled"] and win_start < o["end"] and o["start"] < win_end and (uid, o["start"]) not in seen:
            out.append(_occ(o, o["start"], o["end"] - o["start"]))
    return out


def _occ(ev: dict, start: datetime, dur: timedelta) -> dict:
    return {"uid": ev.get("uid"), "title": ev.get("summary") or "(no title)", "start": start.astimezone(LOCAL_TZ),
            "end": (start + dur).astimezone(LOCAL_TZ), "allday": ev["allday"]}


# ── Full Calendar (notas locales) ─────────────────────────

FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def frontmatter(text: str) -> dict:
    """Frontmatter plano clave: valor (lo que escribe Full Calendar; sin PyYAML)."""
    m = FM_RE.match(text)
    out = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and k and not k.startswith((" ", "-")):
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _hm(v: str | None) -> dtime | None:
    m = re.match(r"(\d{1,2}):(\d{2})", v or "")
    return dtime(int(m.group(1)), int(m.group(2))) if m else None


def _date(v: str | None) -> date | None:
    try:
        return date.fromisoformat((v or "")[:10])
    except ValueError:
        return None


def local_occurrences(folder: Path, win_start: datetime, win_end: datetime) -> list[dict]:
    out = []
    for f in folder.rglob("*.md") if folder.is_dir() else []:
        try:
            fm = frontmatter(f.read_text(errors="replace")[:4000])
        except OSError:
            continue
        if "title" not in fm and "date" not in fm and "startRecur" not in fm:
            continue
        # Tareas hechas (completed con fecha) no se muestran
        if fm.get("completed") not in (None, "", "false", "null"):
            continue
        allday = fm.get("allDay", "").lower() == "true"
        t0, t1 = _hm(fm.get("startTime")), _hm(fm.get("endTime"))
        title = fm.get("title") or f.stem
        days = []
        if fm.get("type") == "recurring":
            wds = {FC_DAYS[x.strip()] for x in fm.get("daysOfWeek", "").strip("[]").split(",") if x.strip() in FC_DAYS}
            first = _date(fm.get("startRecur")) or win_start.date()
            last = _date(fm.get("endRecur"))
            d = max(first, win_start.date())
            while d <= win_end.date() and (last is None or d <= last):
                if d.weekday() in wds:
                    days.append(d)
                d += timedelta(days=1)
        else:
            d0 = _date(fm.get("date"))
            if d0:
                days.append(d0)
        end_date = _date(fm.get("endDate"))
        for d in days:
            if allday or t0 is None:
                s = datetime.combine(d, dtime()).replace(tzinfo=LOCAL_TZ)
                e = datetime.combine((end_date or d) + timedelta(days=1), dtime()).replace(tzinfo=LOCAL_TZ)
                ad = True
            else:
                s = datetime.combine(d, t0).replace(tzinfo=LOCAL_TZ)
                e = datetime.combine(end_date or d, t1 or t0).replace(tzinfo=LOCAL_TZ)
                if e <= s:
                    e = s + timedelta(hours=1) if t1 is None else e + timedelta(days=1)
                ad = False
            if s < win_end and e > win_start:
                out.append({"uid": str(f), "title": title, "start": s, "end": e, "allday": ad, "path": f})
    return out


# ── Fuentes ───────────────────────────────────────────────

def fetch_ics(src: str, cache_dir: Path, force: bool = False) -> str | None:
    """Texto de un .ics (archivo local o URL con cache)."""
    if not re.match(r"(https?|webcal)://", src):
        try:
            return Path(src).expanduser().read_text(errors="replace")
        except OSError:
            return None
    cache = cache_dir / (hashlib.sha1(src.encode()).hexdigest() + ".ics")
    if cache.exists() and not force and time.time() - cache.stat().st_mtime < AGENDA_TTL:
        return cache.read_text(errors="replace")
    try:
        url = re.sub(r"^webcal://", "https://", src)
        req = urllib.request.Request(url, headers={"User-Agent": "desktop-widgets"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode("utf-8", "replace")
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(text)
        tmp.replace(cache)
        return text
    except (OSError, ValueError):
        return cache.read_text(errors="replace") if cache.exists() else None


def sources(conf: dict) -> list[dict]:
    """[{kind: ics|local, src, color, name}] según agenda_source."""
    if conf.get("agenda_source") == "obsidian":
        vault = Path(conf.get("agenda_vault", "")).expanduser()
        try:
            data = json.loads((vault / ".obsidian/plugins/obsidian-full-calendar/data.json").read_text())
        except (OSError, ValueError):
            return []
        out = []
        for s in data.get("calendarSources") or []:
            if s.get("type") == "local" and s.get("directory"):
                out.append({"kind": "local", "src": str(vault / s["directory"]), "color": s.get("color"),
                            "name": s["directory"].strip("/").split("/")[0], "vault": vault})
            elif s.get("type") == "ical" and s.get("url"):
                host = re.sub(r"^\w+://([^/]+).*", r"\1", s["url"])
                out.append({"kind": "ics", "src": s["url"], "color": s.get("color"), "name": host})
        return out
    return [{"kind": "ics", "src": u, "color": None, "name": re.sub(r"^\w+://([^/]+).*", r"\1", u)}
            for u in conf.get("agenda_ics", "").split()]


def upcoming(conf: dict, cache_dir: Path, now: datetime | None = None, days: int = 7,
             force: bool = False) -> dict:
    """{"events": [...], "errors": [nombres], "count": N fuentes} desde ahora hasta `days` días."""
    now = now or datetime.now(LOCAL_TZ)
    win_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    win_end = win_start + timedelta(days=days + 1)
    events, errors = [], []
    srcs = sources(conf)
    for s in srcs:
        if s["kind"] == "local":
            occ = local_occurrences(Path(s["src"]), win_start, win_end)
        else:
            text = fetch_ics(s["src"], cache_dir, force)
            if text is None:
                errors.append(s["name"])
                continue
            try:
                occ = ics_occurrences(text, win_start, win_end)
            except Exception:  # noqa: BLE001 - un .ics roto no tumba la agenda
                errors.append(s["name"])
                continue
        for o in occ:
            o["color"], o["cal"] = s.get("color"), s["name"]
            if s.get("vault") and o.get("path"):
                o["open"] = "obsidian://open?" + urllib.parse.urlencode(
                    {"vault": s["vault"].name, "file": str(o["path"].relative_to(s["vault"]))[:-3]},
                    quote_via=urllib.parse.quote)
            o.pop("path", None)
        events += occ
    # Ya terminados de hoy fuera; los de día completo de hoy quedan
    events = [e for e in events if e["end"] > now or (e["allday"] and e["start"].date() == now.date())]
    events.sort(key=lambda e: (e["start"].date(), not e["allday"], e["start"], e["title"]))
    return {"events": events, "errors": errors, "count": len(srcs)}

