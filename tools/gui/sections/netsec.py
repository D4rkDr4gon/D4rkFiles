"""Network security (GUI): paridad con NetSecView (tools/settings/sections/netsec.py), sobre netguard
(https://github.com/D4rkDr4gon/netguard, opcional). Cuatro pestañas: Hardening (opciones del daemon,
archivos de sistema, access points aprendidos), Ports (qué escucha fuera de loopback), App firewall
(reglas de OpenSnitch) y History.

Sin lógica propia, como la TUI: lee con `netguard … --json` y cambia con sus comandos (ngapi.py). Lo que
la TUI corre en la terminal (sudo: harden, apps apply, instalar) se abre en una terminal suelta; los
cambios que bajan la protección los autentica netguard con polkit (la GUI se oculta mientras tanto).
"""

from __future__ import annotations

import json
import re
import threading
import time

from . import _lib as L

UI: dict = {}
TABS = [("hard", "Hardening"), ("ports", "Ports"), ("apps", "App firewall"), ("hist", "History")]
OPTS = ("dns", "ipv6_unsafe", "autoconnect_unsafe", "ap_check", "ports_warn")
NAMES = {"dns": "Encrypted DNS", "ipv6_unsafe": "IPv6 on unsafe networks", "autoconnect_unsafe": "Autoconnect unsafe networks",
         "ap_check": "Fake network detection", "ports_warn": "Open ports warning"}
BEST = {"dns": "strict", "ipv6_unsafe": "off", "autoconnect_unsafe": "off", "ap_check": "on", "ports_warn": "on"}
DOMAIN_RE = re.compile(r"[a-z0-9.-]+\.[a-z]{2,}")
FILE_STATE = {"ours": "● installed", "old": "◐ outdated", "other": "◐ custom file"}
# pick: "app" | "site" mientras se elige de las sugerencias; items: lo que devolvió `apps suggest`
STATE: dict = {"data": {}, "pick": None, "items": None, "loading": False}


def NG():
    import importlib
    L.tui_module("common")          # deja tools/settings/sections en sys.path (ngapi importa common)
    return importlib.import_module("ngapi")


def call(args: list[str], ok_msg: str = "", auth: bool = False) -> dict:
    """ngapi.call; auth=True si puede bajar la protección (netguard pide polkit: la GUI se oculta)."""
    if auth:
        L.emit({"auth": True})
    try:
        ok, msg = NG().call(*args)
    finally:
        if auth:
            L.emit({"auth": False})
    return L.ok(ok_msg or msg or "Done") if ok else L.fail(msg or "netguard refused it")


def term(args: list[str], title: str) -> dict:
    ng = NG()
    return L.terminal([ng.exe() or "netguard", *args], title)


# ── páginas ──

def page_hard(d: dict) -> list:
    conf = {o["key"]: o for o in d["config"]}
    opts = []
    for key in OPTS:
        o = conf.get(key)
        if o:
            good = o["value"] == BEST[key]
            opts.append(L.item(f"opt:{key}", NAMES[key], sub=o["help"], right=("● " if good else "○ ") + o["value"], on=good, glyph="󰒃"))
    if d["status"].get("config", {}).get("enabled") != "on":
        opts.append(L.info("zones-off", "⚠ Network zones are off", "these only apply while netguard runs: Settings → Firewall → Zones"))
    h = d["harden"]
    sysrows = [
        L.item("sys:sysctl", "Kernel network hardening", sub="no ICMP redirects or source routing, loose rp_filter, martians logged, SYN cookies",
               right=FILE_STATE.get(h.get("sysctl", ""), "○ not installed"), on=h.get("sysctl") == "ours", glyph="󰌆"),
        L.item("sys:privacy", "MAC & IPv6 privacy", sub="one MAC per network (stable on each), random MAC while scanning, temporary IPv6"
               + (" · Wi-Fi MAC via iwd" if h.get("iwd") != "n/a" else ""),
               right=FILE_STATE.get(h.get("privacy", ""), "○ not installed"), on=h.get("privacy") == "ours", glyph="󰌆")]
    n = sum(len(a["bssids"]) for a in d["aps"])
    aps = [L.item(f"ap:{a['uuid']}|{b}", a["name"] or a["uuid"][:8], sub=f"{b} · {a['security']}", glyph="󰖩",
                  actions=[L.action(f"ap:{a['uuid']}|{b}", "Forget", True)]) for a in d["aps"] for b in a["bssids"]]
    return [L.group("Applied per connection by netguard", opts), L.group("System (installed once, sudo)", sysrows),
            L.group(f"Known access points · {n} in {len(d['aps'])} networks",
                    aps or [L.info("noaps", "None learned yet", "learned the first time on each trusted Wi-Fi")])]


def page_ports(d: dict) -> list:
    rows = []
    for p in d["ports"]:
        exp = p["exposure"]
        key = f"port:{p['proto']}:{p['port']}"
        rows.append(L.item(key, f"{p['proto']}/{p['port']} · {p['proc'] or '(root)'}", sub=f"{p['addr']} · {p['unit'] or '?'}",
                           right=exp, on=exp.startswith("blocked"), glyph="󰛳"))
    return [L.group(f"Listening ports · {len(rows)} outside loopback" if rows else "Listening ports",
                    rows or [L.info("none", "Nothing listens outside loopback", "✓")])]


def page_apps(d: dict) -> list:
    st = d["apps"]
    if STATE["pick"]:
        return pick_groups()
    head = []
    if not st.get("installed"):
        head.append(L.button("os-install", "OpenSnitch is not installed", "sudo pacman -S opensnitch, once", "Install"))
    else:
        default = st.get("default")
        pend = st.get("pending_default")
        head.append(L.info("osd", "opensnitchd", "● running" if st.get("active") else "○ stopped"))
        head.append(L.button("default", "Default for unmatched connections",
                             f"{default}" + (f" · pending: {pend} (Apply writes it)" if default != pend else ""),
                             "Deny all" if pend == "allow" else "Allow all", danger=pend == "allow"))
        head += [L.button("add:app", "App rule", "Allow or block an executable", "Add"),
                 L.button("add:site", "Site rule", "Allow or block a domain (and its subdomains)", "Add"),
                 L.button("apply", "Apply rules", "Writes the rules to OpenSnitch (sudo)", "Apply")]
    head.append(L.info("hint", "How rules are built", "apps using the network now, installed apps and your Firefox history · "
                       "escape hatch: sudo systemctl stop opensnitchd"))
    rules = []
    for r in d["rules"]:
        on = r.get("enabled", True)
        rules.append(L.item(f"rule:{r['id']}", f"{r['action']} · {r.get('app') or 'any app'}", sub=r.get("site") or "any site",
                            right="on" if on else "off", on=on and r["action"] == "allow", glyph="󰒃",
                            actions=[L.action(f"flip:{r['id']}", "Allow/deny"), L.action(f"rm:{r['id']}", "Delete", True)]))
    return [L.group("OpenSnitch", head), L.group(f"Rules · {len(d['rules'])}", rules or [L.info("norules", "No rules yet", "")])]


def pick_groups() -> list:
    kind = STATE["pick"]
    back = [L.button("pick:cancel", f"Pick {'an app' if kind == 'app' else 'a site'}", "Or type it by hand", "Cancel"),
            L.item("pick:manual", "✎ Type a path…" if kind == "app" else "✎ Type a domain…", glyph="")]
    items = STATE["items"]
    if items is None:
        return [L.group("New rule", back + [L.info("loading", "Looking for suggestions…", "")])]
    groups = [L.group("New rule", back)]
    if kind == "app":
        for source, title in (("network now", "Using the network now"), ("installed", "Installed apps")):
            rows = [L.item(f"pick:{i['app']}", i["name"], sub=i["app"], glyph="󰀻") for i in items if i["source"] == source]
            if rows:
                groups.append(L.group(title, rows))
    else:
        rows = [L.item(f"pick:{i['site']}", i["site"], sub=f"{i['weight']} visits" if i["weight"] > 1 else "bookmark/known", glyph="󰖟")
                for i in items]
        if rows:
            groups.append(L.group("From Firefox (history and bookmarks)", rows))
    return groups


def event_detail(e: dict) -> str:
    k = e.get("ev", "?")
    if k == "connect":
        return f"{e.get('name')} ({e.get('trust')})" + (f" · AP {e['bssid']}" if e.get("bssid") else "")
    if k == "mode":
        return f"{e.get('frm') or '—'} → {e.get('to')} · {e.get('reason', '')}"
    if k == "killswitch":
        return "armed" if e.get("on") else "disarmed"
    if k in ("vpn_up", "vpn_down", "disconnect"):
        return e.get("name", "")
    if k == "warning":
        return e.get("title", "")
    return ", ".join(f"{a}={b}" for a, b in e.items() if a not in ("t", "ev", "uuid"))


def page_hist(d: dict) -> list:
    rows = []
    for i, e in enumerate(reversed(d["hist"])):
        k = e.get("ev", "?")
        rows.append(L.item(f"ev:{i}", f"{k} · {event_detail(e)}"[:120], sub=time.strftime("%d/%m %H:%M:%S", time.localtime(e.get("t", 0))),
                           on=k in ("connect", "vpn_up"), glyph="󰋚"))
    head = [L.button("clear", "Clear history", "Delete every recorded event", "Clear", danger=True)] if rows else []
    return [L.group(f"Network history · {len(rows)} events" if rows else "Network history",
                    head + (rows or [L.info("none", "No events yet", "")]))]


def load(tab: str) -> dict:
    ng = NG()
    d: dict = {"available": ng.available()}
    if d["available"]:
        if tab == "hard":
            d.update(config=ng.read("config", "list") or [], harden=ng.read("harden") or {},
                     aps=ng.read("ap", "list") or [], status=ng.read("status") or {})
        elif tab == "ports":
            d["ports"] = ng.read("ports") or []
        elif tab == "apps":
            d.update(apps=ng.read("apps", "status") or {}, rules=ng.read("apps", "list") or [])
        else:
            d["hist"] = ng.read("history", "-n", "800") or []
    return d


def get() -> dict:
    tab = UI.get("tab") or "hard"
    d = load(tab)
    STATE["data"] = d
    if not d["available"]:
        groups = [L.group("netguard", [L.button("install", "Install netguard", "Optional in D4rkFiles · git + makepkg (sudo), then its setup",
                                                "Install")])]
    else:
        groups = {"hard": page_hard, "ports": page_ports, "apps": page_apps, "hist": page_hist}[tab](d)
    p = L.page("Network security", "Hardening, open ports, app firewall and network history (netguard)", groups,
               refresh=2 if STATE["pick"] and STATE["items"] is None else (0 if tab == "apps" else 5))
    p.update(tabs=[{"key": k, "label": lbl} for k, lbl in TABS], tab=tab)
    return p


def on_ui(name: str):
    if name == "tab":
        STATE["pick"], STATE["items"] = None, None
    return None


def set_value(key, value):
    return L.fail("Unknown setting")


def rule_form(kind: str, value: str, error: str = "", vals: dict | None = None) -> dict:
    v = vals or {"main": value, "action": "deny", "scope": ""}
    main_label = "EXECUTABLE" if kind == "app" else "DOMAIN (AND ITS SUBDOMAINS)"
    scope_label = "ONLY FOR THIS SITE (EMPTY = ANY)" if kind == "app" else "ONLY FOR THIS APP (EMPTY = EVERY APP)"
    return L.form(f"rule:{kind}", f"{kind.capitalize()} rule", [
        {"name": "main", "label": main_label, "text": v["main"]},
        {"name": "action", "label": "ACTION", "text": v["action"], "choices": [["deny: block it", "deny"], ["allow: always let it through", "allow"]]},
        {"name": "scope", "label": scope_label, "text": v["scope"]}], error=error, ok_label="Add")


def act(key: str, text=None):
    op, _, arg = key.partition(":")
    d = STATE["data"]
    if op == "install":
        if not L.yes(text):
            return L.confirm(key, "Install netguard", "Downloads the pinned version of netguard, builds it with makepkg (sudo) "
                             "and runs its setup.\nSee Settings → Firewall → Zones.", danger=False, ok_label="Install")
        return L.terminal(["bash", str(NG().INSTALLER), "--setup"], "Install netguard")

    # Hardening
    if op == "opt":
        o = next((o for o in d.get("config", []) if o["key"] == arg), None)
        if not o:
            return L.ok()
        values = o["choices"] or [BEST[arg], "on" if BEST[arg] == "off" else "off"]
        if text is None:
            return L.form(key, NAMES[arg], [{"name": "v", "label": "VALUE", "text": o["value"], "choices": [[v, v] for v in values]}],
                          hint=o["help"], ok_label="Apply")
        v = L.parse_form(text).get("v", "")
        if not v or v == o["value"]:
            return L.ok()
        return call(["config", "set", arg, v], f"{NAMES[arg]}: {v} (netguard applies it in a few seconds)", auth=v != BEST[arg])
    if op == "sys":
        on = d.get("harden", {}).get(arg) != "ours"
        title = ("Install " if on else "Remove ") + ("kernel network hardening" if arg == "sysctl" else "MAC & IPv6 privacy")
        if not L.yes(text):
            return L.confirm(key, title, f"Runs `netguard harden {arg} {'on' if on else 'off'}` (sudo)."
                             + ("\nTakes effect on the next connection; Wi-Fi reconnects if iwd restarts.\n"
                                "If your router reserves an IP by MAC, update it." if arg == "privacy" and on else ""),
                             danger=not on, ok_label="Install" if on else "Remove")
        return term(["harden", arg, "on" if on else "off", "-y"], title)
    if op == "ap":
        uuid, _, bssid = arg.partition("|")
        if not L.yes(text):
            return L.confirm(key, "Forget access point", f"Forget {bssid}? It will be asked again the next time.", ok_label="Forget")
        return call(["ap", "forget", uuid, bssid], f"Forgot {bssid} (it will be asked again)")

    # Ports
    if op == "port":
        proto, _, port = arg.partition(":")
        p = next((p for p in d.get("ports", []) if p["proto"] == proto and str(p["port"]) == port), None)
        if not p:
            return L.ok()
        unit = p["unit"]
        info = (f"{p['proto']}/{p['port']} on {p['addr']}\nprocess: {p['proc'] or '(not visible: runs as root)'} "
                f"pid {p['pid'] or '?'}\nunit: {unit or '?'}\n{p['exposure']}")
        if unit.endswith(".service") and not unit.startswith(("user@", "app-", "dbus-:")):
            if not L.yes(text):
                return L.confirm(key, f"Stop {unit}?", info + f"\n\nStops it and disables it at boot (sudo). "
                                 f"Undo: systemctl enable --now {unit}", ok_label="Stop")
            return term(["ports", "--stop", unit, "-y"], f"Stop {unit}")
        return L.text_view(f"Port {p['port']}", info + "\n\nNot a system service: close the app that opened it.")

    # App firewall
    if op == "os-install":
        if not L.yes(text):
            return L.confirm(key, "Install OpenSnitch", "Installs opensnitch and starts opensnitchd (sudo).\n"
                             "Unmatched connections stay ALLOWED until you change the default.", danger=False, ok_label="Install")
        return term(["apps", "install"], "Install OpenSnitch")
    if op == "add":
        STATE["pick"], STATE["items"] = arg, None

        def fetch(kind=arg):
            items = NG().read("apps", "suggest", "apps" if kind == "app" else "sites", timeout=40) or []
            if STATE["pick"] == kind:
                STATE["items"] = items
        threading.Thread(target=fetch, daemon=True).start()
        return L.ok()
    if op == "pick":
        kind = STATE["pick"] or "app"
        if arg == "cancel":
            STATE["pick"], STATE["items"] = None, None
            return L.ok()
        STATE["pick"], STATE["items"] = None, None
        return rule_form(kind, "" if arg == "manual" else arg)
    if op == "rule" and arg in ("app", "site"):
        v = L.parse_form(text)
        v = {"main": v.get("main", "").strip(), "action": v.get("action", "deny"), "scope": v.get("scope", "").strip()}
        if arg == "app" and not v["main"].startswith("/"):
            return rule_form(arg, "", "Full path of the executable (e.g. /usr/lib/firefox/firefox)", v)
        if arg == "site" and not DOMAIN_RE.fullmatch(v["main"].lower()):
            return rule_form(arg, "", "A domain like example.com (subdomains included)", v)
        if v["scope"] and arg == "app" and not DOMAIN_RE.fullmatch(v["scope"].lower()):
            return rule_form(arg, "", "Site: a domain like example.com", v)
        if v["scope"] and arg == "site" and not v["scope"].startswith("/"):
            return rule_form(arg, "", "App: full path of the executable, or empty for every app", v)
        args = ["apps", f"add-{arg}", v["main"]] + (["--allow"] if v["action"] == "allow" else [])
        if v["scope"]:
            args += ["--site" if arg == "app" else "--app", v["scope"]]
        return call(args, "Rule added · Apply writes it")
    if op == "rule":
        r = next((r for r in d.get("rules", []) if r["id"] == arg), None)
        return call(["apps", "disable" if r.get("enabled", True) else "enable", arg]) if r else L.ok()
    if op == "flip":
        return call(["apps", "flip", arg])
    if op == "rm":
        if not L.yes(text):
            return L.confirm(key, "Delete rule", "Delete this OpenSnitch rule?", ok_label="Delete")
        return call(["apps", "remove", arg], "Rule deleted · Apply writes it")
    if op == "default":
        if d.get("apps", {}).get("pending_default") == "allow":
            if not L.yes(text):
                return L.confirm(key, "Block everything not allowed?",
                                 "Unmatched connections will be DENIED: only apps with an allow rule go out.\n"
                                 "netguard adds allow rules for the essentials (DNS, NetworkManager, time, pacman, curl, iwd).\n"
                                 "Add your browser and apps before applying.\n\nEscape hatch: sudo systemctl stop opensnitchd",
                                 ok_label="Deny all")
            return call(["apps", "default", "deny", "-y"], "Default: deny · Apply writes it")
        return call(["apps", "default", "allow"], "Default: allow · Apply writes it", auth=True)
    if op == "apply":
        return term(["apps", "apply"], "Apply the OpenSnitch rules")

    # History
    if op == "ev":
        hist = list(reversed(d.get("hist", [])))
        i = int(arg) if arg.isdigit() else -1
        return L.text_view("Event", json.dumps(hist[i], indent=1, ensure_ascii=False)) if 0 <= i < len(hist) else L.ok()
    if op == "clear":
        if not L.yes(text):
            return L.confirm(key, "Clear network history", "Delete every recorded event?", ok_label="Clear")
        return call(["history", "--clear"], "History cleared")
    return L.ok()
