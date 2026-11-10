"""Wi-Fi (GUI): paridad con WifiView — estado (red, señal, IP, canal y banda, velocidad), radio
on/off, redes visibles (conectadas, guardadas y el resto por señal), conectar (las guardadas y las
abiertas directo; las protegidas piden contraseña, mínimo 8), desconectar, olvidar (con
confirmación), volver a buscar e impala en una kitty."""

from __future__ import annotations

import shutil

from . import _lib as L

UI: dict = {}


def device():
    for line in L.run(["nmcli", "-t", "-f", "DEVICE,TYPE", "dev"]).stdout.splitlines():
        dev, _, kind = line.partition(":")
        if kind == "wifi":
            return dev
    return None


def radio_on() -> bool:
    return L.run(["nmcli", "radio", "wifi"]).stdout.strip() == "enabled"


def saved() -> set[str]:
    out = set()
    for line in L.run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]).stdout.splitlines():
        name, kind = (L.split_terse(line) + [""])[:2]
        if kind == "802-11-wireless":
            out.add(name)
    return out


def networks() -> dict:
    nets = {}
    out = L.run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY,CHAN,RATE", "dev", "wifi", "list", "--rescan", "no"]).stdout
    for line in out.splitlines():
        use, ssid, sig, sec, chan, rate = (L.split_terse(line) + [""] * 6)[:6]
        if not ssid:
            continue
        n = {"ssid": ssid, "active": use == "*", "signal": int(sig or 0), "sec": sec, "chan": int(chan or 0), "rate": rate}
        if ssid not in nets or n["active"] or n["signal"] > nets[ssid]["signal"] and not nets[ssid]["active"]:
            nets[ssid] = n
    return nets


def bars(pct: int) -> str:
    return "󰤨" if pct >= 75 else "󰤥" if pct >= 50 else "󰤢" if pct >= 25 else "󰤟"


def get() -> dict:
    dev, on = device(), radio_on()
    nets = networks() if dev and on else {}
    known = saved()
    cur = next((n for n in nets.values() if n["active"]), None)
    if not dev:
        st = [L.info("st", "Wi-Fi", "○ no Wi-Fi adapter found")]
    elif not on:
        st = [L.info("st", "Wi-Fi", "○ off")]
    elif cur:
        ip = ""
        for ln in L.run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", dev]).stdout.splitlines():
            ip = ln.partition(":")[2].split("/")[0] or ip
        st = [L.info("st", f"● Connected to {cur['ssid']}", f"{bars(cur['signal'])} {cur['signal']}%"),
              L.info("det", "Details", f"{ip or 'no IP yet'} · {dev} · channel {cur['chan']} ({'5 GHz' if cur['chan'] > 14 else '2.4 GHz'}) · {cur['rate']}")]
    else:
        st = [L.info("st", "○ Not connected", dev)]
    ctl = [L.toggle("radio", "Wi-Fi", "Turn the wireless radio on or off", on)]
    if on:
        ctl.append(L.button("rescan", "Rescan", "Look for networks again", "Rescan"))
    if cur:
        ctl.append(L.button("disconnect", "Disconnect", f"From {cur['ssid']}", "Disconnect"))
    if shutil.which("impala"):
        ctl.append(L.button("impala", "Open impala", "The iwd TUI, in a terminal", "Open"))
    rows = []
    for n in sorted(nets.values(), key=lambda n: (not n["active"], n["ssid"] not in known, -n["signal"])):
        secure = n["sec"] not in ("", "--")
        acts = [L.action("disconnect", "Disconnect")] if n["active"] else []
        if n["ssid"] in known:
            acts.append(L.action(f"forget:{n['ssid']}", "Forget", True))
        rows.append(L.item(f"connect:{n['ssid']}", n["ssid"],
                           sub=f"{n['sec'] if secure else 'open'} · {n['signal']}% · {'5G' if n['chan'] > 14 else '2.4G'}",
                           right="● connected" if n["active"] else ("saved" if n["ssid"] in known else ""),
                           glyph=bars(n["signal"]), on=n["active"], actions=acts))
    groups = [L.group("Status", st), L.group("Wi-Fi", ctl)]
    if on:
        groups.append(L.group(f"Networks · {len(nets)} · {len(known)} saved", rows or [L.info("none", "No networks found", "")]))
    return L.page("Wi-Fi", "NetworkManager", groups, refresh=8)


def set_value(key: str, value):
    if key == "radio":
        L.run(["nmcli", "radio", "wifi", "on" if value else "off"])
        return L.ok("Wi-Fi " + ("on" if value else "off"))
    return L.fail("Unknown setting")


def connect(ssid: str, password: str = "") -> dict:
    if ssid in saved() and not password:
        args = ["nmcli", "con", "up", "id", ssid]
    else:
        args = ["nmcli", "dev", "wifi", "connect", ssid] + (["password", password] if password else [])
    r = L.run(args, timeout=60)
    if r.returncode == 0:
        return L.ok(f"Connected to {ssid}")
    err = (r.stderr or r.stdout).strip().splitlines()
    return L.fail(err[-1] if err else "connection failed")


def act(key: str, text=None):
    op, _, arg = key.partition(":")
    if op == "rescan":
        L.run(["nmcli", "dev", "wifi", "rescan"], timeout=15)
        return L.ok("Scanning…")
    if op == "disconnect":
        dev = device()
        r = L.run(["nmcli", "dev", "disconnect", dev]) if dev else None
        return L.ok("Wi-Fi disconnected") if r and r.returncode == 0 else L.fail((r.stderr.strip() if r else "") or "No Wi-Fi device")
    if op == "forget":
        if arg not in saved():
            return L.fail("That network is not saved")
        if not L.yes(text):
            return L.confirm(key, "Forget network", f"Forget {arg} and its saved password?", ok_label="Forget")
        L.run(["nmcli", "con", "delete", "id", arg])
        return L.ok(f"{arg} forgotten")
    if op == "impala":
        L.detach(["kitty", "--class", "impala", "--title", "Wi-Fi", "-e", "impala"])
        return L.ok()
    if op == "connect":
        n = networks().get(arg)
        if n and n["active"]:
            return L.ok(f"Already connected to {arg}")
        if text is None:
            if arg in saved() or not n or n["sec"] in ("", "--"):
                return connect(arg)
            return {"ask": {"key": key, "title": f"Connect to {arg}",
                            "fields": [{"name": "password", "label": f"PASSWORD ({n['sec']})", "text": "", "secret": True}]}}
        pw = L.parse_form(text).get("password", "") if text.lstrip().startswith("{") else text
        if len(pw) < 8:
            return {"ask": {"key": key, "title": f"Connect to {arg}", "error": "WPA passwords have at least 8 characters",
                            "fields": [{"name": "password", "label": "PASSWORD", "text": "", "secret": True}]}}
        return connect(arg, pw)
    return L.ok()
