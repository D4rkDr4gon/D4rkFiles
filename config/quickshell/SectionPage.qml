pragma ComponentBehavior: Bound
import QtQuick
import Quickshell.Io
import Quickshell

// Página genérica de una sección de Settings. El backend (tools/gui/bridge.py
// → tools/gui/sections/<id>.py) devuelve un JSON con grupos de filas:
//   toggle | choice | slider | button | info | item     (ver sections/_lib.py)
// La lista se actualiza EN EL LUGAR (setProperty por fila) cuando la estructura
// no cambia: sin reconstruir delegados no hay saltos de scroll ni parpadeos.
Item {
    id: root

    property string bridge: ""
    property string section: ""
    property string title: ""
    property string subtitle: ""
    property int refreshMs: 0
    property bool busy: false
    property string status: ""
    property bool active: true                    // la página está a la vista (pausa el refresco)
    property var queue: []
    property alias asking: forms.asking           // {key, label, secret, placeholder}
    property string sig: ""
    signal closeRequested()
    property var tabs: []                         // [{key, label}] pestañas de la página
    property string tab: ""
    property string searchHint: ""                // != "" → buscador arriba de la lista
    function setTab(k) { tab = k; enqueue(["set", "__tab", JSON.stringify(k)], "__tab") }
    Timer { id: searchDebounce; interval: 220; onTriggered: root.enqueue(["set", "__search", JSON.stringify(searchBox.text)], "__search") }

    // ── datos ─────────────────────────────────────────────
    ListModel { id: rows }

    function norm(type, r) {
        return {
            type: type, key: r.key ?? "", kind: r.kind ?? "", name: r.name ?? "", desc: r.desc ?? "",
            value: JSON.stringify(r.value === undefined ? null : r.value), custom: !!r.custom,
            options: JSON.stringify(r.options ?? []), lo: r.lo ?? 0, hi: r.hi ?? 1, step: r.step ?? 1,
            danger: !!r.danger, sub: r.sub ?? "", tail: r.right ?? "", glyph: r.glyph ?? "",
            image: r.image ?? "", swatch: r.color ?? "", on: !!r.on, actions: JSON.stringify(r.actions ?? []), label: r.label ?? ""
        }
    }

    function applyData(d) {
        title = d.title ?? ""
        subtitle = d.subtitle ?? ""
        refreshMs = d.refresh ?? 0
        tabs = d.tabs ?? []
        tab = d.tab ?? ""
        searchHint = d.search ?? ""
        const flat = []
        for (const g of (d.groups ?? [])) {
            if (g.name) flat.push(norm("header", { key: "h:" + g.name, name: g.name }))
            for (const r of g.rows) flat.push(norm("row", r))
        }
        const s = flat.map(r => r.key + ":" + r.kind).join("|")
        if (s === sig && rows.count === flat.length) {
            for (let i = 0; i < flat.length; i++) {
                const cur = rows.get(i), nxt = flat[i]
                for (const role in nxt) if (cur[role] !== nxt[role]) rows.setProperty(i, role, nxt[role])
            }
        } else {
            rows.clear()
            for (const r of flat) rows.append(r)
            sig = s
        }
    }

    // ── backend compartido (Backend.qml → bridge.py serve) ──
    property var cache: ({})                      // sección → último JSON (se muestra al instante al volver)
    property bool getInflight: false
    property string getSection: ""
    property bool holding: false

    function hold(on) {
        if (on && !holding) { holding = true; Backend.acquire() }
        else if (!on && holding) { holding = false; Backend.release() }
    }
    // al dejar una sección (cambio de sección, ventana cerrada) se avisa: deshace vistas previas en vivo
    property string shownSection: ""
    property bool standalone: false               // ventana suelta (ToolWindow) o dentro de Settings
    function enter() { shownSection = section; Backend.request(section, "set", ["__standalone", JSON.stringify(standalone)], () => {}) }
    function leave() { if (shownSection !== "") Backend.request(shownSection, "leave", [], () => {}); shownSection = "" }
    onActiveChanged: { hold(active); if (active) { enter(); reload() } else leave() }
    Component.onDestruction: { leave(); hold(false) }

    function reload() {
        if (getInflight && getSection === section) return
        getSection = section
        getInflight = true
        const want = section
        Backend.request(want, "get", [], (res, sec) => {
            if (getSection === want) getInflight = false
            if (!res || res.ok === false && !res.groups) { if (want === root.section) root.status = res ? (res.msg ?? "") : ""; return }
            root.cache[want] = res
            if (want !== root.section) return            // respuesta vieja: ya se pidió la de ahora
            root.applyData(res)
        })
    }

    onSectionChanged: {
        leave(); if (active) enter()
        sig = ""; rows.clear(); title = ""; subtitle = ""; queue = []; status = ""; asking = null; viewer = null
        if (cache[section]) applyData(cache[section])        // al instante; el refresco lo corrige
        getInflight = false
        reload()
    }
    Component.onCompleted: { hold(active); if (active) enter(); reload() }

    Timer {
        interval: Math.max(root.refreshMs, 500)
        running: root.refreshMs > 0 && root.active && !root.busy
        repeat: true
        onTriggered: root.reload()
    }

    property int runInflight: 0
    property alias viewer: forms.viewer           // {title, body}: texto largo (diffs, logs)
    function onResult(r, sec) {
        if (sec === "" || sec === section) {
            status = r.msg ?? ""
            if (r.ask) asking = r.ask
            if (r.text) viewer = r.text
            if (r.close) closeRequested()
        }
        runInflight = Math.max(0, runInflight - 1)
        if (queue.length > 0) runNext()
        else { busy = false; reload() }
    }

    // ── acciones (se encolan; una a la vez) ──────────────
    function runNext() {
        busy = true
        const j = queue.shift()
        runInflight += 1
        const sec = section
        Backend.request(sec, j[0], j.slice(1), (res, s) => root.onResult(res || { ok: false, msg: "" }, sec))
    }
    function enqueue(job, coalesceKey) {
        if (coalesceKey) queue = queue.filter(j => j[1] !== coalesceKey)
        queue.push(job)
        if (runInflight === 0) runNext()
    }
    function setValue(key, value) { enqueue(["set", key, JSON.stringify(value)], key) }
    function act(key, text) {
        status = ""
        enqueue(text === undefined ? ["act", key] : ["act", key, text])
    }

    // ── cabecera ─────────────────────────────────────────
    Item {
        id: head
        width: parent.width
        height: 92 + (root.tabs.length > 0 ? 46 : 0) + (root.searchHint !== "" ? 50 : 0)
        Column {
            x: 2; y: 46 - height / 2
            spacing: 6
            Text { text: root.title; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 30; font.bold: true }
            Text {
                visible: text.length > 0
                text: root.subtitle
                color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 13
            }
        }
        // pestañas
        Row {
            id: tabRow
            visible: root.tabs.length > 0
            x: 0; y: 92
            spacing: 4
            Repeater {
                model: root.tabs
                delegate: Rectangle {
                    id: tb
                    required property var modelData
                    readonly property bool sel: root.tab === modelData.key
                    height: 32; width: tbT.implicitWidth + 28
                    radius: Theme.radius
                    color: sel ? Theme.foreground : (tbA.containsMouse ? Theme.tint10 : "transparent")
                    Behavior on color { ColorAnimation { duration: Motion.snap } }
                    Text {
                        id: tbT; anchors.centerIn: parent; text: tb.modelData.label
                        color: tb.sel ? Theme.background : Theme.foreground
                        font.family: Theme.fontUi; font.pixelSize: 13; font.bold: tb.sel
                    }
                    MouseArea { id: tbA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.setTab(tb.modelData.key) }
                }
            }
        }
        // buscador
        Rectangle {
            visible: root.searchHint !== ""
            x: 0; y: 92 + (root.tabs.length > 0 ? 46 : 0)
            width: parent.width; height: 38
            radius: Theme.radius; color: "transparent"
            border.width: 1; border.color: searchBox.activeFocus ? Theme.foreground : Theme.lineStrong
            Text { x: 12; anchors.verticalCenter: parent.verticalCenter; text: "󰍉"; color: Theme.muted; font.family: Theme.fontMono; font.pixelSize: 15 }
            TextInput {
                id: searchBox
                anchors { fill: parent; leftMargin: 36; rightMargin: 12 }
                verticalAlignment: TextInput.AlignVCenter
                color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 14
                clip: true
                onTextChanged: searchDebounce.restart()
                Keys.onEscapePressed: { if (text) text = ""; else root.closeRequested() }
            }
            Text {
                anchors { fill: searchBox }
                verticalAlignment: Text.AlignVCenter
                visible: searchBox.text.length === 0
                text: root.searchHint
                color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 14
            }
        }
        Text {
            anchors { right: parent.right; rightMargin: 4 }
            y: 46 - height / 2
            text: root.busy ? "Working…" : root.status
            color: root.busy ? Theme.foreground : Theme.muted
            font.family: Theme.fontUi; font.pixelSize: 13
            opacity: text.length > 0 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Motion.snap } }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.lineSoft }
    }

    // ── lista ────────────────────────────────────────────
    ListView {
        id: list
        y: head.height
        width: parent.width
        height: parent.height - head.height
        clip: true
        model: rows
        boundsBehavior: Flickable.StopAtBounds
        reuseItems: false
        cacheBuffer: 600

        delegate: Item {
            id: row
            required property int index
            required property string type
            required property string key
            required property string kind
            required property string name
            required property string desc
            required property string value
            required property bool custom
            required property string options
            required property real lo
            required property real hi
            required property real step
            required property bool danger
            required property string sub
            required property string tail
            required property string glyph
            required property string image
            required property string swatch
            required property bool on
            required property string actions
            required property string label

            readonly property bool isHeader: type === "header"
            readonly property bool isItem: kind === "item"
            readonly property var v: { try { return JSON.parse(value) } catch (e) { return null } }
            readonly property var opts: { try { return JSON.parse(options) } catch (e) { return [] } }
            readonly property var acts: { try { return JSON.parse(actions) } catch (e) { return [] } }

            width: list.width
            height: isHeader ? 48 : isItem ? (image !== "" ? 78 : 58) : 50

            // encabezado de grupo: "01 ·" estilo editorial no, simple y en versalitas
            Text {
                visible: row.isHeader
                x: 2; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
                text: row.name.toUpperCase()
                color: Theme.muted
                font.family: Theme.fontUi; font.pixelSize: 11; font.bold: true; font.letterSpacing: 1.4
            }

            // fondo al pasar el mouse
            Rectangle {
                visible: !row.isHeader
                anchors.fill: parent; anchors.topMargin: 1; anchors.bottomMargin: 1
                radius: Theme.radius
                color: Theme.tint5
                opacity: hover.hovered && (row.isItem || row.kind === "button") ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: Motion.snap } }
            }
            HoverHandler { id: hover; enabled: !row.isHeader }
            Rectangle {
                visible: !row.isHeader
                anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.lineSoft
            }

            // imagen o ícono de un item
            Rectangle {
                id: thumb
                visible: row.isItem && (row.image !== "" || row.glyph !== "")
                x: 6; anchors.verticalCenter: parent.verticalCenter
                width: row.image !== "" ? 96 : 34; height: row.image !== "" ? 58 : 34
                radius: Theme.radius
                color: row.swatch !== "" ? row.swatch : Theme.tint5
                border.width: row.swatch !== "" ? 1 : 0; border.color: Theme.line
                clip: true
                Image {
                    anchors.fill: parent
                    visible: row.image !== ""
                    source: row.image !== "" ? row.image : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    sourceSize.width: 192
                }
                Text {
                    anchors.centerIn: parent
                    visible: row.image === "" && row.swatch === ""
                    text: row.glyph
                    color: row.on ? Theme.foreground : Theme.inkMuted
                    font.family: Theme.fontMono; font.pixelSize: 18
                }
            }

            Column {
                anchors {
                    left: parent.left; leftMargin: row.isItem && thumb.visible ? thumb.width + 20 : (row.custom ? 20 : 4)
                    right: ctl.left; rightMargin: 16; verticalCenter: parent.verticalCenter
                }
                visible: !row.isHeader
                spacing: 3
                Text {
                    width: parent.width
                    text: row.isItem ? row.label : row.name
                    elide: Text.ElideRight
                    color: row.danger ? Theme.error : Theme.foreground
                    font.family: Theme.fontUi; font.pixelSize: 15
                    font.bold: row.isItem && row.on
                }
                Text {
                    width: parent.width
                    visible: text.length > 0
                    text: row.isItem ? row.sub : row.desc
                    elide: Text.ElideRight
                    color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                }
            }
            // marca de "lo define el tema"
            Rectangle {
                visible: row.custom && !row.isHeader
                x: 4; anchors.verticalCenter: parent.verticalCenter
                width: 5; height: 5; radius: 3; color: Theme.foreground
            }

            // ── control de la derecha ──
            Row {
                id: ctl
                visible: !row.isHeader
                anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                spacing: 12
                layoutDirection: Qt.LeftToRight

                // acciones secundarias de un item (aparecen al pasar el mouse)
                Repeater {
                    model: row.acts
                    delegate: Item {
                        id: act
                        required property var modelData
                        width: actText.implicitWidth + 20; height: 26
                        opacity: hover.hovered ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: Motion.snap } }
                        Rectangle {
                            anchors.fill: parent; radius: Theme.radius
                            color: actArea.containsMouse ? Theme.foreground : "transparent"
                            border.width: 1; border.color: act.modelData.danger ? Theme.error : Theme.line
                            Behavior on color { ColorAnimation { duration: Motion.snap } }
                        }
                        Text {
                            id: actText
                            anchors.centerIn: parent
                            text: act.modelData.label
                            color: actArea.containsMouse ? Theme.background : (act.modelData.danger ? Theme.error : Theme.inkMuted)
                            font.family: Theme.fontUi; font.pixelSize: 12
                        }
                        MouseArea { id: actArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.act(act.modelData.key) }
                    }
                }

                Text {
                    visible: row.isItem && row.tail !== ""
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.tail
                    color: row.on ? Theme.foreground : Theme.muted
                    font.family: Theme.fontUi; font.pixelSize: 13
                }
                Text {
                    visible: row.kind === "info"
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.v === null ? "" : String(row.v)
                    color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 14
                }
                Toggle {
                    visible: row.kind === "toggle"
                    anchors.verticalCenter: parent.verticalCenter
                    checked: row.v === true
                    onToggled: v => root.setValue(row.key, v)
                }
                Segmented {
                    visible: row.kind === "choice"
                    anchors.verticalCenter: parent.verticalCenter
                    options: row.opts
                    current: row.v === null ? "" : String(row.v)
                    onPicked: v => root.setValue(row.key, v)
                }
                Row {
                    visible: row.kind === "slider"
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 14
                    Slider {
                        id: sl
                        anchors.verticalCenter: parent.verticalCenter
                        width: 200
                        from: row.lo; to: row.hi; step: row.step
                        value: row.v === null ? row.lo : Number(row.v)
                        onCommitted: v => root.setValue(row.key, row.step >= 1 ? Math.round(v) : Number(v.toFixed(3)))
                    }
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 50; horizontalAlignment: Text.AlignRight
                        text: row.step >= 1 ? Math.round(sl.shown) : sl.shown.toFixed(2)
                        color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13; font.bold: true
                    }
                }
                Item {
                    visible: row.kind === "button"
                    anchors.verticalCenter: parent.verticalCenter
                    width: btnText.implicitWidth + 28; height: 28
                    Rectangle {
                        anchors.fill: parent; radius: Theme.radius
                        color: btnArea.containsMouse ? Theme.foreground : "transparent"
                        border.width: 1; border.color: row.danger ? Theme.error : Theme.lineStrong
                        Behavior on color { ColorAnimation { duration: Motion.snap } }
                    }
                    Text {
                        id: btnText
                        anchors.centerIn: parent
                        text: row.label
                        color: btnArea.containsMouse ? Theme.background : (row.danger ? Theme.error : Theme.foreground)
                        font.family: Theme.fontUi; font.pixelSize: 13
                    }
                    MouseArea { id: btnArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.act(row.key) }
                }
            }

            // click en toda la fila de un item = acción principal
            MouseArea {
                anchors.fill: parent
                anchors.rightMargin: row.acts.length > 0 ? 6 + ctl.width : 0
                enabled: row.isItem
                cursorShape: Qt.PointingHandCursor
                onClicked: root.act(row.key)
            }
        }
    }

    Text {
        anchors.centerIn: list
        visible: rows.count === 0
        text: root.getInflight ? "Loading…" : "Nothing to show"
        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 14
    }

    // ── formularios, confirmaciones y visor de texto (FormLayer.qml) ──
    FormLayer {
        id: forms
        anchors.fill: parent
        onSubmitted: (key, text) => root.act(key, text)
    }
}
