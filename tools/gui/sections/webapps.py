"""Webapps (GUI): paridad con WebappsView — las PWAs instaladas (firefoxpwa) con su detalle
(página, manifiesto, id, si está en webapps.conf); abrir (cierra la ventana), nueva (URL → detect()
busca el manifiesto o arma uno → nombre y página de inicio con validación → webapps.sh),
reinstalar (desinstala y vuelve a instalar desde webapps.conf) y borrar (con confirmación; la saca
también del conf). Instalar corre como trabajo con log; si falla una nueva, se quita del conf."""

from __future__ import annotations

import re
import sys

from . import _lib as L

UI: dict = {}
STATE: dict = {"info": None}


def W():
    p = str(L.TOOLS)
    if p not in sys.path:
        sys.path.insert(0, p)
    import webapps_tui
    return webapps_tui


def get() -> dict:
    w = W()
    apps = w.installed()
    names = w.conf_names()
    rows = []
    for a in apps:
        inconf = a["name"] in names
        rows.append(L.item(f"open:{a['id']}", a["name"], sub=f"{a['url']} · manifest {a['manifest'] or '—'}"[:110],
                           right="in webapps.conf" if inconf else "not in webapps.conf", glyph="󰖟", on=inconf,
                           actions=[L.action(f"open:{a['id']}", "Open"), L.action(f"reinstall:{a['id']}", "Reinstall"),
                                    L.action(f"del:{a['id']}", "Delete", True)]))
    missing = sorted(names - {a["name"] for a in apps})
    groups = [L.group("Webapps", [L.button("new", "New webapp", "From a URL: uses its manifest or generates one", "New")])]
    groups += L.job_group("webapps")
    groups.append(L.group(f"Installed · {len(apps)}", rows or [L.info("none", "No webapps yet", "New webapp creates one")]))
    if missing:
        groups.append(L.group("In webapps.conf but not installed", [
            L.item(f"install:{n}", n, sub="Listed in webapps.conf", glyph="󰖟", actions=[L.action(f"install:{n}", "Install")]) for n in missing]))
    return L.page("Webapps", "PWAs on Firefox · open them from the launcher", groups, refresh=2 if L.job_running("webapps") else 10)


def set_value(key, value):
    return L.fail("Unknown setting")


def install(name: str, new: bool = False, uninstall_id: str = "") -> dict:
    w = W()
    steps = []
    if uninstall_id:
        steps.append(("user", ["firefoxpwa", "site", "uninstall", "--quiet", uninstall_id], "Uninstall"))
    steps.append(("user", ["bash", str(w.WEBAPPS_SH), name], f"Install {name}"))

    def after(ok: bool):
        if not ok and new:
            w.conf_remove(name)   # si falló, no dejar la entrada en el conf
    return L.job_start("webapps", f"Installing {name}", steps, after) or L.ok(f"Installing {name}…")


def act(key: str, text=None):
    w = W()
    op, _, arg = key.partition(":")
    if op == "log":
        return L.text_view("Webapps log", L.job_text(arg))
    apps = {a["id"]: a for a in w.installed()}
    if op == "open" and arg in apps:
        L.detach(["firefoxpwa", "site", "launch", arg])
        return {"ok": True, "msg": "", "close": True}
    if L.job_running("webapps") and op in ("new", "create", "reinstall", "install"):
        return L.fail("Wait for the current install to finish")
    if op == "new":
        if text is None:
            return L.form("new", "New webapp", [{"name": "url", "label": "URL", "text": ""}], hint="https://…")
        url = L.parse_form(text).get("url", "").strip()
        if not url:
            return L.form("new", "New webapp", [{"name": "url", "label": "URL", "text": ""}], error="The URL is missing")
        url = url if re.match(r"^https?://", url) else f"https://{url}"
        try:
            info = w.detect(url)
        except Exception as e:  # noqa: BLE001
            return L.fail(f"Could not open {url}: {e}")
        STATE["info"] = info
        return create_form(info["name"], info["url"])
    if op == "create" and STATE["info"]:
        info = STATE["info"]
        v = L.parse_form(text)
        name = v.get("name", "").replace("|", "").strip()
        taken = w.conf_names() | {a["name"] for a in apps.values()}
        err = "The name is missing" if not name else (f"There is already a webapp called {name}" if name in taken else "")
        if err:
            return create_form(v.get("name", ""), v.get("url", ""), err)
        w.conf_append(name, info["manifest"], v.get("url", "").strip() or info["url"], info["icon"])
        STATE["info"] = None
        return install(name, new=True)
    if op == "install" and arg in w.conf_names():
        return install(arg)
    if op == "reinstall" and arg in apps:
        a = apps[arg]
        if a["name"] not in w.conf_names():
            return L.fail(f"{a['name']} is not in webapps.conf: don't know how to reinstall it")
        return install(a["name"], uninstall_id=arg)
    if op == "del" and arg in apps:
        a = apps[arg]
        if not L.yes(text):
            return L.confirm(key, "Delete webapp", f"Delete {a['name']}? Its session will be lost.", ok_label="Delete")
        r = L.run(["firefoxpwa", "site", "uninstall", "--quiet", arg], timeout=60)
        if r.returncode != 0:
            return L.fail(f"Could not delete {a['name']}")
        if a["name"] in w.conf_names():
            w.conf_remove(a["name"])
        return L.ok(f"{a['name']} deleted")
    return L.ok()


def create_form(name: str, url: str, error: str = "") -> dict:
    info = STATE["info"]
    hint = f"Manifest: {info['manifest']}" if info["manifest"] else f"Not a PWA: a manifest will be generated. Icon: {info['icon']}"
    return L.form("create", "Create webapp", [{"name": "name", "label": "NAME", "text": name},
                                               {"name": "url", "label": "START PAGE", "text": url}], hint=hint, error=error)
