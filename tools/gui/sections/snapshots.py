"""Snapshots (GUI): paridad con SnapshotsView — Timeshift. La lista se lee sin root
(/timeshift/snapshots/*/info.json); crear, restaurar y borrar van por el helper root de la GUI
(una huella por sesión), crear y restaurar como trabajo en segundo plano con log."""

from __future__ import annotations

from . import _lib as L

UI: dict = {}
TAGS = {"O": "on demand", "B": "boot", "H": "hourly", "D": "daily", "W": "weekly", "M": "monthly"}


def T():
    return L.tui_module("snapshots")


def get() -> dict:
    items = T().snapshots()
    rows = [L.item(f"snap:{s['name']}", s["name"], sub=" ".join(TAGS.get(c, c) for c in s["tags"]) + (f" · {s['comment']}" if s["comment"] else ""),
                   glyph="󰄄", actions=[L.action(f"restore:{s['name']}", "Restore", True), L.action(f"del:{s['name']}", "Delete", True)])
            for s in items]
    return L.page("Snapshots", "Timeshift · create, restore and delete ask for your fingerprint once per GUI session",
                  L.job_group("snapshots") + [
                      L.group("Snapshots", [L.button("new", "New snapshot", f"{len(items)} snapshots", "Create")]),
                      L.group("List", rows or [L.info("none", "No snapshots yet", "")])],
                  refresh=2 if L.job_running("snapshots") else 0)


def set_value(key, value):
    return L.fail("Unknown setting")


def act(key: str, text=None):
    op, _, arg = key.partition(":")
    if op == "new":
        if text is None:
            return L.form("new", "New snapshot", [{"name": "comment", "label": "COMMENT (OPTIONAL)", "text": ""}],
                          hint="e.g. before kernel update", ok_label="Create")
        c = L.parse_form(text).get("comment", "").strip() or "from Settings"
        return L.job_start("snapshots", "New snapshot", [("root", ["timeshift", "--create", "--comments", c, "--scripted"], "Timeshift")])
    if op == "log":
        return L.text_view("Snapshots", L.job_text("snapshots") or "(empty)")
    if op == "restore":
        if not L.yes(text):
            return L.confirm(key, "Restore snapshot", f"Restore the system to {arg}?\nThe machine reboots afterwards. "
                             "Files in /home are not touched.", ok_label="Restore and reboot")
        return L.job_start("snapshots", f"Restore {arg}", [("root", ["timeshift", "--restore", "--snapshot", arg, "--scripted", "--yes"],
                                                            "Timeshift restore")])
    if op == "del":
        if not L.yes(text):
            return L.confirm(key, "Delete snapshot", f"Delete snapshot {arg}?", ok_label="Delete")
        return L.root_ok([["timeshift", "--delete", "--snapshot", arg, "--scripted"]], f"Deleted {arg}")
    return L.ok()
