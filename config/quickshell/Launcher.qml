pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

// Launcher: apps (Mod+Space), emoji (Mod+E) y power (Mod+L). Misma lógica que
// tools/launcher_tui.py (favoritas de ~/.config/dotfiles/launcher-favorites.txt,
// historial de ~/.local/state/dotfiles/launcher-history.json), con otra cara.
Scope {
    id: root

    property bool shown: false
    property string mode: "apps"          // apps | emoji | power | workspaces
    property string query: ""
    property int pending: -1              // índice de la acción de power que espera confirmación

    readonly property string home: Quickshell.env("HOME")
    readonly property string dots: home + "/.local/share/dotfiles"   // el repo (manifest/links.tsv)
    readonly property string bridge: dots + "/tools/gui/bridge.py"
    readonly property string confDir: (Quickshell.env("XDG_CONFIG_HOME") || home + "/.config") + "/dotfiles"
    readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || home + "/.local/state") + "/dotfiles"

    // dmenu: lo abre scripts/dmenu.sh con rutas de entrada/salida
    property string dmIn: ""
    property string dmOut: ""
    property string dmPrompt: "Menu"
    property string dmPlaceholder: ""
    property bool dmNoCustom: false
    property bool dmIndex: false
    property var dmItems: []
    property bool dmDone: true

    function finishDmenu(choice) {
        if (dmDone) return
        dmDone = true
        dmFinish.command = ["sh", "-c", '[ -n "$3" ] && printf %s "$3" > "$1"; touch "$2"', "_", dmOut, dmOut + ".done", choice]
        dmFinish.running = true
    }
    function openDmenu(inFile, outFile, prompt, placeholder, noCustom, index) {
        dmIn = inFile; dmOut = outFile; dmPrompt = prompt || "Menu"; dmPlaceholder = placeholder
        dmNoCustom = noCustom === "1"; dmIndex = index === "1"
        dmItems = []; dmDone = false
        dmLoader.command = ["cat", inFile]
        dmLoader.running = true
        mode = "dmenu"; query = ""; pending = -1; shown = true
    }
    Process { id: dmFinish }
    Process {
        id: dmLoader
        stdout: StdioCollector { onStreamFinished: root.dmItems = text.split("\n").filter(l => l.length > 0) }
    }

    function open(m) { if (mode === "dmenu") finishDmenu(""); mode = m; query = ""; pending = -1; shown = true; if (m === "workspaces") wsLoader.running = true }
    function close() { if (mode === "dmenu") finishDmenu(""); shown = false }
    function toggle(m) { (shown && mode === m) ? close() : open(m) }

    IpcHandler { target: "launcher";       function toggle(): void { root.toggle("apps") } }
    IpcHandler { target: "launcher-emoji"; function toggle(): void { root.toggle("emoji") } }
    IpcHandler { target: "launcher-power"; function toggle(): void { root.toggle("power") } }
    IpcHandler {
        target: "launcher-dmenu"
        function open(inFile: string, outFile: string, prompt: string, placeholder: string, noCustom: string, index: string): void {
            root.openDmenu(inFile, outFile, prompt, placeholder, noCustom, index)
        }
    }
    IpcHandler { target: "launcher-ws"; function toggle(): void { root.toggle("workspaces") } }

    property var wsRows: []
    Process {
        id: wsLoader
        command: ["python3", root.bridge, "ws-list"]
        stdout: StdioCollector { onStreamFinished: { try { root.wsRows = JSON.parse(text) } catch (e) {} } }
    }

    // ── datos ─────────────────────────────────────────────
    FileView { id: favFile;  path: root.confDir + "/launcher-favorites.txt"; watchChanges: true; onFileChanged: reload() }
    FileView { id: histFile; path: root.stateDir + "/launcher-history.json"; watchChanges: true; onFileChanged: reload() }
    FileView { id: emojiFile; path: root.dots + "/tools/launcher_emoji.txt" }

    readonly property var favorites: {
        const out = {}
        for (const l of (favFile.text() || "").split("\n")) {
            const s = l.trim()
            if (s && !s.startsWith("#")) out[s.toLowerCase()] = true
        }
        return out
    }
    readonly property var history: {
        try { return JSON.parse(histFile.text() || "{}") } catch (e) { return {} }
    }
    readonly property var emoji: {
        const out = []
        for (const l of (emojiFile.text() || "").split("\n")) {
            const i = l.indexOf(" ")
            if (i > 0) out.push({ label: l.slice(i + 1), glyph: l.slice(0, i) })
        }
        return out
    }

    readonly property var power: [
        { label: "Lock",      sub: "lock the screen",              glyph: "󰌾", cmd: ["bash", dots + "/scripts/lock-screen.sh"], confirm: false },
        { label: "Suspend",   sub: "sleep, keeps the session",     glyph: "󰒲", cmd: ["systemctl", "suspend"], confirm: false },
        { label: "Log out",   sub: "close the session",            glyph: "󰍃", cmd: [dots + "/hypr/scripts/hypr-dispatch", "exit"], confirm: true },
        { label: "Reboot",    sub: "restart the computer",         glyph: "󰜉", cmd: ["systemctl", "reboot"], confirm: true },
        { label: "Power off", sub: "shut down the computer",       glyph: "󰐥", cmd: ["systemctl", "poweroff"], confirm: true, danger: true }
    ]

    function frecency(e) {
        if (!e) return 0
        const age = Math.max(0, (Date.now() / 1000 - e[1]) / 86400)
        return Math.min(e[0], 50) * (age < 7 ? 1 : age < 30 ? 0.5 : 0.2)
    }

    function score(q, name, extra) {
        const n = name.toLowerCase()
        if (n.startsWith(q)) return 100
        if (n.includes(" " + q)) return 80
        if (n.includes(q)) return 60
        if ((extra || "").toLowerCase().includes(q)) return 20
        return 0
    }

    // Lista a mostrar según el modo y lo escrito
    readonly property var results: {
        const q = query.trim().toLowerCase()
        if (mode === "dmenu") {
            const out = []
            dmItems.forEach((l, i) => { if (!q || l.toLowerCase().includes(q)) out.push({ label: l, sub: "", glyph: "󰁔", idx: i }) })
            if (!dmNoCustom && query.trim() && !out.some(o => o.label === query.trim()))
                out.push({ label: query.trim(), sub: "use what you typed", glyph: "󰏫", idx: -1 })
            return out.slice(0, 80)
        }
        if (mode === "workspaces")
            return wsRows.filter(w => !q || w.label.toLowerCase().includes(q) || w.sub.toLowerCase().includes(q))
        if (mode === "power")
            return power.filter(p => !q || p.label.toLowerCase().includes(q))
        if (mode === "emoji") {
            const out = []
            for (const e of emoji) {
                if (!q || e.label.toLowerCase().includes(q)) out.push(e)
                if (out.length >= 60) break
            }
            return out
        }
        if (!q) return []                     // apps: solo el buscador hasta que se escribe algo
        const rows = []
        for (const e of DesktopEntries.applications.values) {
            if (e.noDisplay) continue
            const fav = !!favorites[e.name.toLowerCase()]
            const use = frecency(history[e.id + ".desktop"])
            let s = q ? score(q, e.name, (e.genericName || "") + " " + (e.comment || "") + " " + (e.keywords || []).join(" ")) : 1
            if (s <= 0) continue
            s += (fav ? 30 : 0) + use
            rows.push({ label: e.name, sub: e.comment || e.genericName || "", entry: e, fav: fav, s: s })
        }
        rows.sort((a, b) => b.s - a.s || a.label.localeCompare(b.label))
        return rows.slice(0, 60)
    }

    Process { id: runner }
    Process { id: helper }

    function activate(i) {
        if (i < 0 || i >= results.length) return
        const r = results[i]
        if (mode === "apps") {
            helper.command = ["python3", bridge, "bump", r.entry.id + ".desktop"]
            helper.running = true
            r.entry.execute()
            close()
        } else if (mode === "emoji") {
            runner.command = ["wl-copy", r.glyph]
            runner.running = true
            close()
        } else if (mode === "dmenu") {
            finishDmenu(dmIndex ? (r.idx >= 0 ? String(r.idx) : "") : r.label)
            shown = false
        } else if (mode === "workspaces") {
            runner.command = [dots + "/hypr/scripts/hypr-dispatch", "workspace", r.ws]
            runner.running = true
            close()
        } else if (r.confirm && pending !== i) {
            pending = i                      // primer enter pide confirmar, el segundo ejecuta
        } else {
            runner.command = r.cmd
            runner.running = true
            close()
        }
    }

    // ── ventana ───────────────────────────────────────────
    PanelWindow {
        id: win
        screen: Quickshell.screens.find(s => s.name === Hyprland.focusedMonitor?.name) ?? Quickshell.screens[0]
        visible: root.shown || card.opacity > 0.01
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; left: true; right: true; bottom: true }
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "dotfiles-launcher"
        WlrLayershell.keyboardFocus: root.shown ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

        // velo suave detrás: clic afuera cierra
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, 0.28)
            opacity: root.shown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Motion.normal; easing.type: Motion.out } }
            MouseArea { anchors.fill: parent; onClicked: root.close() }
        }

        Rectangle {
            id: card
            width: Math.min(720, parent.width - 48)
            readonly property bool empty: list.count === 0
            height: empty ? search.y + search.height + 18 : Math.min(Math.max(search.height + 24 + list.contentHeight + 24, 140), 540)
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.round(parent.height * 0.22) + (root.shown ? 0 : 14)
            radius: Theme.radius + 2
            color: Qt.alpha(Theme.background, Math.max(Theme.opacity, 0.92))
            border.width: 1
            border.color: Theme.line
            opacity: root.shown ? 1 : 0
            scale: root.shown ? 1 : 0.985
            transformOrigin: Item.Top

            Behavior on opacity { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            Behavior on y { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            Behavior on scale { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            Behavior on height { NumberAnimation { duration: Motion.move; easing.type: Motion.out } }

            MouseArea { anchors.fill: parent }   // que el clic dentro de la tarjeta no cierre

            // buscador
            Item {
                id: search
                x: 22; y: 18
                width: parent.width - 44
                height: 44

                Text {
                    id: lens
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.mode === "apps" ? "󰍉" : root.mode === "emoji" ? "󰞅" : root.mode === "workspaces" ? "󰍹" : root.mode === "dmenu" ? "󰁔" : "󰐥"
                    color: Theme.foreground
                    font.family: Theme.fontMono
                    font.pixelSize: 20
                }
                TextInput {
                    id: input
                    anchors { left: lens.right; leftMargin: 14; right: parent.right; verticalCenter: parent.verticalCenter }
                    color: Theme.foreground
                    font.family: Theme.fontUi
                    font.pixelSize: 19
                    clip: true
                    focus: true
                    selectByMouse: true
                    text: root.query
                    onTextChanged: { root.query = text; root.pending = -1; list.currentIndex = 0 }
                    Connections { target: root; function onShownChanged() { if (root.shown) { input.text = ""; input.forceActiveFocus() } } }

                    Keys.onPressed: event => {
                        const down = event.key === Qt.Key_Down || (event.modifiers & Qt.ControlModifier && (event.key === Qt.Key_J || event.key === Qt.Key_N))
                        const up = event.key === Qt.Key_Up || (event.modifiers & Qt.ControlModifier && (event.key === Qt.Key_K || event.key === Qt.Key_P))
                        if (event.key === Qt.Key_Escape) { root.close(); event.accepted = true }
                        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) { root.activate(list.currentIndex); event.accepted = true }
                        else if (down) { list.currentIndex = Math.min(list.currentIndex + 1, list.count - 1); root.pending = -1; event.accepted = true }
                        else if (up) { list.currentIndex = Math.max(list.currentIndex - 1, 0); root.pending = -1; event.accepted = true }
                    }
                }
                Text {
                    anchors.fill: input
                    verticalAlignment: Text.AlignVCenter
                    visible: input.text.length === 0
                    text: root.mode === "apps" ? "Search apps…" : root.mode === "emoji" ? "Search emoji…" : root.mode === "workspaces" ? "Go to workspace…" : root.mode === "dmenu" ? (root.dmPlaceholder || root.dmPrompt) : "Lock, suspend, log out, reboot, power off…"
                    color: Theme.muted
                    font: input.font
                }
            }

            Rectangle {
                id: sep
                x: 22; y: search.y + search.height + 8
                width: parent.width - 44; height: 1
                color: Theme.lineSoft
                visible: !card.empty
            }

            ListView {
                id: list
                x: 12; y: sep.y + 9
                width: parent.width - 24
                height: card.height - y - 12
                clip: true
                model: root.results
                currentIndex: 0
                boundsBehavior: Flickable.StopAtBounds
                highlightMoveDuration: Motion.move
                highlightMoveVelocity: -1
                highlightResizeDuration: 0

                // la selección es una sola pastilla que se desliza entre filas
                highlight: Rectangle {
                    radius: Theme.radius
                    color: Theme.foreground
                }

                delegate: Item {
                    id: row
                    required property int index
                    required property var modelData
                    width: list.width
                    height: 46
                    readonly property bool selected: ListView.isCurrentItem
                    readonly property bool asking: root.mode === "power" && root.pending === index

                    Image {
                        id: icon
                        visible: root.mode === "apps"
                        x: 12; anchors.verticalCenter: parent.verticalCenter
                        width: 28; height: 28
                        sourceSize: Qt.size(56, 56)
                        source: root.mode === "apps" ? Quickshell.iconPath(row.modelData.entry.icon, "application-x-executable") : ""
                    }
                    Text {
                        visible: root.mode !== "apps"
                        x: 12; width: 28
                        anchors.verticalCenter: parent.verticalCenter
                        horizontalAlignment: Text.AlignHCenter
                        text: row.modelData.glyph ?? ""
                        color: row.selected ? Theme.background : (row.modelData.danger ? Theme.error : Theme.foreground)
                        font.family: root.mode === "emoji" ? "Noto Color Emoji" : Theme.fontMono
                        font.pixelSize: root.mode === "emoji" ? 22 : 20
                    }
                    Column {
                        anchors { left: parent.left; leftMargin: 54; right: tag.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
                        spacing: 1
                        Text {
                            width: parent.width
                            text: row.asking ? row.modelData.label + " — press enter again to confirm" : row.modelData.label
                            elide: Text.ElideRight
                            color: row.asking ? Theme.error : (row.selected ? Theme.background : Theme.foreground)
                            font.family: Theme.fontUi
                            font.pixelSize: 15
                            font.bold: row.selected
                        }
                        Text {
                            width: parent.width
                            visible: text.length > 0
                            text: row.modelData.sub ?? ""
                            elide: Text.ElideRight
                            color: row.selected ? Qt.alpha(Theme.background, 0.7) : Theme.muted
                            font.family: Theme.fontUi
                            font.pixelSize: 12
                        }
                    }
                    Text {
                        id: tag
                        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                        text: row.modelData.fav ? "★" : ""
                        color: Theme.warn
                        font.pixelSize: 14
                    }
                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        onPositionChanged: list.currentIndex = row.index
                        onClicked: { list.currentIndex = row.index; root.activate(row.index) }
                    }
                }
            }
        }
    }
}
