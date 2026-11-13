import QtQuick

// Finanzas (GUI de Gastos): app propia, no una SectionPage. Barra lateral con patrimonio, vistas y
// cuentas; cada vista es un tablero armado con los datos que devuelve tools/gui/sections/expenses.py
// (get() → {view, data, sidebar, monthLabel…}). Formularios, confirmaciones y validaciones son los del
// backend (act() → ask) y se muestran con FormLayer, igual que en cualquier sección.
// Manage embebe la sección Finances (cuentas, categorías, cotizaciones, import, CSV).
Item {
    id: root

    property bool active: true
    property bool standalone: true
    signal closeRequested()

    readonly property string section: "expenses"
    property var info: null                       // última respuesta de get()
    readonly property var side: info ? info.sidebar : null
    property string view: "overview"
    property bool busy: false
    property string status: ""
    property bool inflight: false
    property var queue: []

    readonly property var views: [
        { key: "overview", label: "Overview", glyph: "󰕮", month: true },
        { key: "transactions", label: "Transactions", glyph: "󰈍", month: true },
        { key: "budgets", label: "Budgets", glyph: "󰠠", month: true },
        { key: "cards", label: "Cards", glyph: "󰆛", month: false },
        { key: "plans", label: "Installments", glyph: "󰃭", month: false },
        { key: "scheduled", label: "Scheduled", glyph: "󰑖", month: false },
        { key: "reports", label: "Reports", glyph: "󰄨", month: true },
        { key: "manage", label: "Manage", glyph: "󰒓", month: false }
    ]
    readonly property var cur: views.find(v => v.key === view) ?? views[0]

    // ── backend ──────────────────────────────────────────
    property bool holding: false
    function hold(on) {
        if (on && !holding) { holding = true; Backend.acquire() }
        else if (!on && holding) { holding = false; Backend.release() }
    }
    onActiveChanged: { hold(active); if (active) reload() }
    Component.onCompleted: {
        hold(active)
        Backend.request(section, "set", ["__standalone", "true"], () => {})
        setUi("view", view)
    }
    Component.onDestruction: hold(false)

    function reload() {
        if (inflight) return
        inflight = true
        Backend.request(section, "get", [], res => {
            inflight = false
            if (!res || res.ok === false) { status = res ? (res.msg ?? "") : ""; return }
            if (res.view !== view) { view = res.view }
            info = res
            present(res)
        })
    }
    // La vista nueva se crea con sus datos como propiedad inicial (createObject) y la anterior se
    // destruye con los suyos: así ningún enlace ve datos de otra vista a mitad del cambio.
    property Item viewItem: null
    function present(res) {
        if (viewItem && viewItem.viewKey === res.view) { viewItem.d = res.data; return }
        const comp = ({ overview: vOverview, transactions: vTxns, budgets: vBudgets, cards: vCards, plans: vPlans,
                        scheduled: vScheduled, reports: vReports })[res.view]
        const old = viewItem
        viewItem = comp ? comp.createObject(host, { d: res.data, viewKey: res.view }) : null
        if (old) old.destroy()
    }
    function setUi(name, value) {
        Backend.request(section, "set", ["__" + name, JSON.stringify(value)], () => root.reload())
    }
    function go(v) {
        if (v === view && info && info.view === v) return
        view = v
        setUi("view", v)
    }
    function filter(name, value) { setUi(name, value) }
    function act(key, text) {
        status = ""
        queue.push(text === undefined ? ["act", key] : ["act", key, text])
        if (!busy) runNext()
    }
    function runNext() {
        if (queue.length === 0) { busy = false; reload(); return }
        busy = true
        const j = queue.shift()
        Backend.request(section, j[0], j.slice(1), res => {
            res = res || { ok: false, msg: "" }
            root.status = res.msg ?? ""
            if (res.ask) forms.asking = res.ask
            if (res.text) forms.viewer = res.text
            if (res.close) root.closeRequested()
            root.runNext()
        })
    }
    Timer { interval: 30000; repeat: true; running: root.active && !root.busy && !forms.open; onTriggered: root.reload() }

    // ── teclado ──────────────────────────────────────────
    focus: true
    Keys.onPressed: event => {
        if (forms.open || picker.visible) return
        const t = event.text
        if (t >= "1" && t <= "8") { go(views[Number(t) - 1].key); event.accepted = true }
        else if ((event.key === Qt.Key_Left || t === "h") && cur.month) { act("month:-1"); event.accepted = true }
        else if ((event.key === Qt.Key_Right || t === "l") && cur.month) { act("month:1"); event.accepted = true }
        else if (t === "n") { act("txn:new"); event.accepted = true }
        else if (t === "r") { reload(); event.accepted = true }
    }

    // ── piezas ───────────────────────────────────────────
    component Label: Text {
        color: Theme.foreground
        font.family: Theme.fontUi
        font.pixelSize: 14
        elide: Text.ElideRight
    }
    component Caps: Text {
        color: Theme.muted
        font.family: Theme.fontUi
        font.pixelSize: 11
        font.bold: true
        font.letterSpacing: 1.3
        font.capitalization: Font.AllUppercase
    }
    component Btn: Item {
        id: btn
        property string text: ""
        property string glyph: ""
        property bool primary: false
        property bool danger: false
        property bool small: false
        signal clicked()
        width: bRow.implicitWidth + (small ? 18 : 26)
        height: small ? 26 : 32
        Rectangle {
            anchors.fill: parent
            radius: Theme.radius
            color: btn.primary ? (bA.containsMouse ? Qt.alpha(Theme.foreground, 0.85) : Theme.foreground)
                               : (bA.containsMouse ? Theme.tint10 : "transparent")
            border.width: btn.primary ? 0 : 1
            border.color: btn.danger ? Theme.error : Theme.lineStrong
            Behavior on color { ColorAnimation { duration: Motion.snap } }
        }
        Row {
            id: bRow
            anchors.centerIn: parent
            spacing: 6
            Text {
                visible: btn.glyph !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: btn.glyph
                color: btn.primary ? Theme.background : btn.danger ? Theme.error : Theme.foreground
                font.family: Theme.fontMono; font.pixelSize: btn.small ? 12 : 14
            }
            Text {
                visible: btn.text !== ""
                anchors.verticalCenter: parent.verticalCenter
                text: btn.text
                color: btn.primary ? Theme.background : btn.danger ? Theme.error : Theme.foreground
                font.family: Theme.fontUi; font.pixelSize: btn.small ? 12 : 13; font.bold: btn.primary
            }
        }
        MouseArea { id: bA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: btn.clicked() }
    }
    // Tarjeta rellena con título en versalitas (como los widgets de escritorio)
    component Panel: Rectangle {
        id: pnl
        property string title: ""
        property string note: ""
        default property alias content: inner.data
        implicitHeight: inner.y + inner.implicitHeight + 16
        radius: Theme.radius + 2
        color: Theme.tint5
        border.width: 1
        border.color: Theme.lineSoft
        Caps { id: pT; x: 16; y: 15; visible: pnl.title !== ""; text: pnl.title }
        Text {
            visible: pnl.note !== ""
            anchors { right: parent.right; rightMargin: 16; verticalCenter: pT.verticalCenter }
            text: pnl.note
            color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
        }
        Column {
            id: inner
            x: 16
            y: pnl.title !== "" ? 40 : 16
            width: pnl.width - 32
            spacing: 6
        }
    }
    component Kpi: Rectangle {
        id: kpi
        property string label: ""
        property string value: ""
        property string sub: ""
        property string tone: ""
        property real pct: -1
        height: 98
        radius: Theme.radius + 2
        color: Theme.tint5
        border.width: 1; border.color: Theme.lineSoft
        readonly property color toneColor: tone === "ok" ? Theme.ok : tone === "warn" ? Theme.warn : tone === "error" ? Theme.error : Theme.foreground
        Column {
            x: 16; y: 14; width: parent.width - 32
            spacing: 5
            Caps { text: kpi.label }
            Text {
                width: parent.width; elide: Text.ElideRight
                text: kpi.value
                color: kpi.tone === "error" || kpi.tone === "warn" ? kpi.toneColor : Theme.foreground
                font.family: Theme.fontUi; font.pixelSize: 22; font.bold: true
            }
            Text {
                width: parent.width; elide: Text.ElideRight
                text: kpi.sub
                color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
            }
        }
        Meter { visible: kpi.pct >= 0; x: 16; y: parent.height - 12; width: parent.width - 32; value: kpi.pct; tone: kpi.tone }
    }
    // Barra de avance: relleno por estado y, opcional, una marca (el ritmo del mes)
    component Meter: Item {
        id: m
        property real value: 0
        property real mark: -1
        property string tone: ""
        property color fill: tone === "ok" ? Theme.ok : tone === "warn" ? Theme.warn : tone === "error" ? Theme.error : Theme.primary
        height: 6
        Rectangle { anchors.fill: parent; radius: height / 2; color: Theme.tint10 }
        Rectangle {
            height: parent.height; radius: height / 2
            width: Math.max(value > 0 ? height : 0, Math.min(1, m.value) * parent.width)
            color: m.fill
            Behavior on width { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
        }
        Rectangle {
            visible: m.mark > 0 && m.mark < 1
            x: m.mark * parent.width - 1; y: -3
            width: 2; height: parent.height + 6; radius: 1
            color: Theme.foreground
        }
    }
    // Ícono de categoría en un círculo
    component Badge: Rectangle {
        property string glyph: ""
        property bool dim: false
        width: 32; height: 32; radius: 16
        color: Theme.tint10
        Text {
            anchors.centerIn: parent
            text: parent.glyph
            color: Theme.foreground
            opacity: parent.dim ? 0.55 : 1
            font.family: Theme.fontUi; font.pixelSize: 15
        }
    }
    // Movimiento: ícono, descripción, categoría · cuenta, monto; clic = editar
    component TxnRow: Item {
        id: tr
        property var t: ({})
        property bool showDate: false
        signal open()
        signal remove()
        width: parent ? parent.width : 0
        height: 50
        Rectangle { anchors.fill: parent; radius: Theme.radius; color: Theme.tint5; opacity: trH.hovered ? 1 : 0 }
        HoverHandler { id: trH }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: tr.open() }
        Badge { id: trB; x: 6; anchors.verticalCenter: parent.verticalCenter; glyph: tr.t.icon ?? ""; dim: !!tr.t.future }
        Column {
            anchors { left: trB.right; leftMargin: 12; right: trAmt.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 2
            Row {
                width: parent.width
                spacing: 6
                Label {
                    width: Math.min(implicitWidth, parent.width - (trInst.visible ? trInst.width + 6 : 0) - (trFut.visible ? trFut.width + 6 : 0))
                    text: tr.t.desc ?? ""
                    color: tr.t.future ? Theme.inkMuted : Theme.foreground
                }
                Rectangle {
                    id: trInst
                    visible: (tr.t.inst ?? "") !== ""
                    anchors.verticalCenter: parent.verticalCenter
                    width: trInstT.implicitWidth + 12; height: 18; radius: 9
                    color: Theme.tint10
                    Text { id: trInstT; anchors.centerIn: parent; text: tr.t.inst ?? ""; color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 11 }
                }
                Rectangle {
                    id: trFut
                    visible: !!tr.t.future
                    anchors.verticalCenter: parent.verticalCenter
                    width: trFutT.implicitWidth + 12; height: 18; radius: 9
                    color: "transparent"; border.width: 1; border.color: Theme.line
                    Text { id: trFutT; anchors.centerIn: parent; text: "scheduled"; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 11 }
                }
            }
            Text {
                width: parent.width; elide: Text.ElideRight
                text: [tr.showDate ? tr.t.dlabel : "", tr.t.cat, tr.t.acct, tr.t.extra, tr.t.note].filter(x => x).join("  ·  ")
                color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
            }
        }
        Text {
            id: trAmt
            anchors { right: trDel.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
            text: tr.t.amount ?? ""
            color: tr.t.type === "income" ? Theme.ok : tr.t.type === "transfer" ? Theme.inkMuted : Theme.foreground
            opacity: tr.t.future ? 0.6 : 1
            font.family: Theme.fontUi; font.pixelSize: 14; font.bold: tr.t.type !== "transfer"
        }
        Text {
            id: trDel
            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
            width: 18
            text: "󰆴"
            opacity: trH.hovered ? (trDA.containsMouse ? 1 : 0.55) : 0
            color: trDA.containsMouse ? Theme.error : Theme.foreground
            font.family: Theme.fontMono; font.pixelSize: 14
            MouseArea { id: trDA; anchors.fill: parent; anchors.margins: -6; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: tr.remove() }
        }
    }
    // Barras verticales de a dos series (a: relleno de acento, b: tenue); valores 0..1
    component Columns: Item {
        id: cols
        property var model: []
        property string aKey: "expense"
        property string bKey: "income"
        property string aLabel: "Expenses"
        property string bLabel: "Income"
        property bool normalized: false
        readonly property real peak: normalized ? 1 : Math.max(1, ...model.map(x => Math.max(x[aKey] ?? 0, x[bKey] ?? 0)))
        height: 196
        Row {
            spacing: 14
            Repeater {
                model: [{ c: Theme.primary, t: cols.aLabel }, { c: Qt.alpha(Theme.foreground, 0.32), t: cols.bLabel }]
                Row {
                    spacing: 6
                    Rectangle { width: 10; height: 10; radius: 3; color: modelData.c; anchors.verticalCenter: parent.verticalCenter }
                    Text { text: modelData.t; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12 }
                }
            }
        }
        Row {
            id: colRow
            y: 26
            width: parent.width; height: parent.height - 26
            readonly property real slot: cols.model.length ? width / cols.model.length : 0
            Repeater {
                model: cols.model
                Item {
                    width: colRow.slot; height: colRow.height
                    readonly property real bw: Math.min(16, (width - 14) / 2)
                    Rectangle { anchors.fill: parent; anchors.bottomMargin: 20; radius: Theme.radius; color: modelData.sel ? Theme.tint5 : "transparent" }
                    Row {
                        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 22 }
                        spacing: 3
                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: bw; radius: Math.min(4, bw / 2)
                            height: Math.max(2, (modelData[cols.aKey] ?? 0) / cols.peak * (colRow.height - 34))
                            color: Theme.primary
                            Behavior on height { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
                        }
                        Rectangle {
                            anchors.bottom: parent.bottom
                            width: bw; radius: Math.min(4, bw / 2)
                            height: Math.max(2, (modelData[cols.bKey] ?? 0) / cols.peak * (colRow.height - 34))
                            color: Qt.alpha(Theme.foreground, 0.32)
                            Behavior on height { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
                        }
                    }
                    Text {
                        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom }
                        text: modelData.label
                        color: modelData.sel ? Theme.foreground : Theme.muted
                        font.family: Theme.fontUi; font.pixelSize: 11; font.bold: !!modelData.sel
                    }
                }
            }
        }
    }
    // Barras verticales de una serie con etiqueta arriba (resúmenes, compromiso de cuotas)
    component Bars: Row {
        id: bars
        property var model: []
        property int barHeight: 120
        height: barHeight + 44
        readonly property real slot: model.length ? width / model.length : 0
        Repeater {
            model: bars.model
            Item {
                width: bars.slot; height: bars.height
                Text {
                    anchors { horizontalCenter: parent.horizontalCenter; bottom: bar.top; bottomMargin: 4 }
                    text: modelData.amount
                    color: modelData.state === "open" ? Theme.foreground : Theme.muted
                    font.family: Theme.fontUi; font.pixelSize: 11; font.bold: modelData.state === "open"
                }
                Rectangle {
                    id: bar
                    anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 38 }
                    width: Math.min(34, bars.slot - 12)
                    height: Math.max(2, (modelData.h ?? 0) * (bars.barHeight - 16))
                    radius: Math.min(5, width / 3)
                    color: modelData.state === "closed" ? Qt.alpha(Theme.foreground, 0.32)
                         : modelData.state === "future" ? Qt.alpha(Theme.primary, 0.42) : Theme.primary
                    Behavior on height { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
                }
                Column {
                    anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: modelData.label + (modelData.known ? " •" : "")
                        color: modelData.state === "open" ? Theme.foreground : Theme.inkMuted
                        font.family: Theme.fontUi; font.pixelSize: 12; font.bold: modelData.state === "open"
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        visible: (modelData.sub ?? "") !== ""
                        text: modelData.sub ?? ""
                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 10
                    }
                }
            }
        }
    }
    component Chip: Rectangle {
        id: chip
        property string text: ""
        property bool sel: false
        signal clicked()
        height: 30; width: chT.implicitWidth + 24
        radius: Theme.radius
        color: sel ? Theme.foreground : (chA.containsMouse ? Theme.tint10 : "transparent")
        border.width: 1; border.color: sel ? Theme.foreground : Theme.lineStrong
        Behavior on color { ColorAnimation { duration: Motion.snap } }
        Text { id: chT; anchors.centerIn: parent; text: chip.text; color: chip.sel ? Theme.background : Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13 }
        MouseArea { id: chA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
    }
    // Fila simple de lista: ícono, título, detalle y algo a la derecha
    component Line: Item {
        id: ln
        property string glyph: ""
        property string title: ""
        property string sub: ""
        property string amount: ""
        property string rightSub: ""
        property color rightColor: Theme.foreground
        property bool dim: false
        property bool clickable: true
        signal clicked()
        width: parent ? parent.width : 0
        height: 48
        Rectangle { anchors.fill: parent; radius: Theme.radius; color: Theme.tint5; opacity: lnH.hovered && ln.clickable ? 1 : 0 }
        HoverHandler { id: lnH }
        MouseArea { anchors.fill: parent; enabled: ln.clickable; cursorShape: Qt.PointingHandCursor; onClicked: ln.clicked() }
        Badge { id: lnB; visible: ln.glyph !== ""; x: 6; anchors.verticalCenter: parent.verticalCenter; glyph: ln.glyph; dim: ln.dim }
        Column {
            anchors { left: lnB.visible ? lnB.right : parent.left; leftMargin: lnB.visible ? 12 : 6; right: lnR.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 2
            Label { width: parent.width; text: ln.title; color: ln.dim ? Theme.inkMuted : Theme.foreground }
            Text { width: parent.width; visible: text !== ""; elide: Text.ElideRight; text: ln.sub; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12 }
        }
        Column {
            id: lnR
            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
            spacing: 2
            Text { anchors.right: parent.right; text: ln.amount; color: ln.rightColor; opacity: ln.dim ? 0.6 : 1; font.family: Theme.fontUi; font.pixelSize: 14; font.bold: true }
            Text { anchors.right: parent.right; visible: text !== ""; text: ln.rightSub; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 11 }
        }
    }
    component Empty: Text {
        width: parent ? parent.width : 0
        height: 44
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: Text.AlignHCenter
        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 13
    }

    // ── barra lateral ────────────────────────────────────
    Item {
        id: sidebarBox
        width: 236
        height: parent.height

        Column {
            id: sideTop
            width: parent.width - 16
            spacing: 4
            Text { text: "Finances"; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 26; font.bold: true }
            Item { width: 1; height: 8 }
            Caps { text: "Net worth" }
            Text {
                width: parent.width; elide: Text.ElideRight
                text: root.side ? root.side.net : "…"
                color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 21; font.bold: true
            }
            Text {
                text: root.side ? `assets ${root.side.assets}  ·  debt ${root.side.debt}` : ""
                color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
            }
            Item { width: 1; height: 14 }
            Repeater {
                model: root.views
                Rectangle {
                    id: nav
                    readonly property bool sel: root.view === modelData.key
                    width: sideTop.width; height: 36
                    radius: Theme.radius
                    color: sel ? Theme.foreground : (navA.containsMouse ? Theme.tint10 : "transparent")
                    Behavior on color { ColorAnimation { duration: Motion.snap } }
                    Text {
                        id: navG; x: 12; anchors.verticalCenter: parent.verticalCenter; width: 20
                        text: modelData.glyph
                        color: nav.sel ? Theme.background : Theme.inkMuted
                        font.family: Theme.fontMono; font.pixelSize: 16
                    }
                    Text {
                        anchors { left: navG.right; leftMargin: 10; verticalCenter: parent.verticalCenter }
                        text: modelData.label
                        color: nav.sel ? Theme.background : Theme.foreground
                        font.family: Theme.fontUi; font.pixelSize: 14; font.bold: nav.sel
                    }
                    Text {
                        anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                        text: index + 1
                        color: nav.sel ? Qt.alpha(Theme.background, 0.6) : Theme.muted
                        font.family: Theme.fontUi; font.pixelSize: 11
                        opacity: navA.containsMouse || nav.sel ? 1 : 0
                    }
                    MouseArea { id: navA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.go(modelData.key) }
                }
            }
            Item { width: 1; height: 14 }
            Rectangle { width: parent.width; height: 1; color: Theme.lineSoft }
            Item { width: 1; height: 8 }
        }

        Flickable {
            anchors { top: sideTop.bottom; bottom: parent.bottom; left: parent.left; right: parent.right; rightMargin: 16 }
            clip: true
            contentHeight: accCol.implicitHeight + 8
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: accCol
                width: parent.width
                spacing: 2
                Repeater {
                    model: root.side ? root.side.groups : []
                    Column {
                        width: accCol.width
                        spacing: 0
                        Item {
                            width: parent.width; height: 28
                            Caps { anchors.bottom: parent.bottom; anchors.bottomMargin: 6; text: modelData.name }
                            Text {
                                anchors { right: parent.right; rightMargin: 6; bottom: parent.bottom; bottomMargin: 6 }
                                text: modelData.totalFmt
                                color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 11
                            }
                        }
                        Repeater {
                            model: modelData.accounts
                            Rectangle {
                                id: acc
                                width: accCol.width; height: 30
                                radius: Theme.radius
                                color: accA.containsMouse ? Theme.tint10 : "transparent"
                                Text {
                                    anchors { left: parent.left; leftMargin: 6; right: accB.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                                    text: modelData.name
                                    elide: Text.ElideRight
                                    color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                                }
                                // clic en el nombre: sus movimientos (o la tarjeta); clic en el monto: Set balance (ajuste)
                                MouseArea {
                                    id: accA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        if (modelData.card) { root.filter("card", modelData.id); root.go("cards") }
                                        else { root.filter("facc", String(modelData.id)); root.go("transactions") }
                                    }
                                }
                                Rectangle {
                                    anchors { fill: accB; leftMargin: -6; rightMargin: -4; topMargin: -3; bottomMargin: -3 }
                                    radius: Theme.radius
                                    color: "transparent"
                                    border.width: 1; border.color: accBA.containsMouse ? Theme.lineStrong : "transparent"
                                }
                                Row {
                                    id: accB
                                    anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
                                    spacing: 5
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: "󰏫"
                                        visible: accA.containsMouse || accBA.containsMouse
                                        color: Theme.muted; font.family: Theme.fontMono; font.pixelSize: 12
                                    }
                                    Text {
                                        text: modelData.balance + (modelData.cur ? " " + modelData.cur : "")
                                        color: modelData.neg ? Theme.error : Theme.foreground
                                        font.family: Theme.fontUi; font.pixelSize: 13
                                    }
                                }
                                MouseArea {
                                    id: accBA; anchors.fill: accB; anchors.margins: -4
                                    hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: root.act("acc:balance:" + modelData.id)
                                }
                            }
                        }
                    }
                }
            }
        }
        Rectangle { anchors.right: parent.right; width: 1; height: parent.height; color: Theme.lineSoft }
    }

    // ── contenido ────────────────────────────────────────
    Item {
        id: main
        anchors { left: sidebarBox.right; leftMargin: 24; right: parent.right; top: parent.top; bottom: parent.bottom }

        Item {
            id: topBar
            visible: root.view !== "manage"
            width: parent.width
            height: root.view === "manage" ? 0 : 52
            Text {
                id: vTitle
                anchors.verticalCenter: parent.verticalCenter
                text: root.cur.label
                color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 24; font.bold: true
            }
            Row {
                visible: root.cur.month
                anchors { left: vTitle.right; leftMargin: 18; verticalCenter: parent.verticalCenter }
                spacing: 4
                Btn { small: true; glyph: "󰅁"; onClicked: root.act("month:-1") }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 132; horizontalAlignment: Text.AlignHCenter
                    text: root.info ? root.info.monthLabel : ""
                    color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 14
                }
                Btn { small: true; glyph: "󰅂"; onClicked: root.act("month:1") }
                Btn { small: true; visible: root.info && !root.info.isThisMonth; text: "Today"; onClicked: root.act("month:0") }
            }
            Row {
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: 8
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.min(implicitWidth, 260); elide: Text.ElideRight
                    text: root.busy ? "Working…" : root.status
                    color: root.busy ? Theme.foreground : Theme.muted
                    font.family: Theme.fontUi; font.pixelSize: 12
                }
                Btn { glyph: "󰁔"; text: "Transfer"; onClicked: root.act("txn:new:type:transfer") }
                Btn { glyph: "󰁝"; text: "Income"; onClicked: root.act("txn:new:type:income") }
                Btn { primary: true; glyph: "󰐕"; text: "Expense"; onClicked: root.act("txn:new") }
            }
        }

        Item {
            id: host
            anchors { top: topBar.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: parent.bottom }
            visible: root.view !== "manage"
        }
        Loader {
            id: body
            anchors { top: topBar.bottom; topMargin: root.view === "manage" ? 0 : 10; left: parent.left; right: parent.right; bottom: parent.bottom }
            active: root.view === "manage" || root.viewItem === null
            sourceComponent: root.view === "manage" ? vManage : vLoading
        }
    }

    // ── vistas ───────────────────────────────────────────
    Component { id: vLoading; Empty { text: root.status || "Loading…" } }

    Component {
        id: vManage
        SectionPage {
            section: "finances"
            active: root.active && root.view === "manage"
            standalone: true
            onCloseRequested: root.closeRequested()
        }
    }

    Component {
        id: vOverview
        Flickable {
            id: fl
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            contentHeight: ovCol.implicitHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: ovCol
                width: fl.width
                spacing: 14
                Row {
                    width: parent.width; spacing: 12
                    Repeater {
                        model: fl.d.kpis
                        Kpi {
                            width: (ovCol.width - 36) / 4
                            label: modelData.label; value: modelData.value; sub: modelData.sub; tone: modelData.tone
                            pct: modelData.pct ?? -1
                        }
                    }
                }
                Row {
                    width: parent.width; spacing: 14
                    Panel {
                        width: (parent.width - 14) / 2
                        height: Math.max(implicitHeight, trendP.implicitHeight)
                        title: "Spending by category"
                        note: root.info ? root.info.monthLabel : ""
                        Repeater {
                            model: fl.d.categories
                            Item {
                                width: parent.width; height: 34
                                Text { id: cI; y: 2; text: modelData.icon; font.family: Theme.fontUi; font.pixelSize: 14; color: Theme.foreground }
                                Label { x: 26; y: 2; width: parent.width - 130; text: modelData.name; font.pixelSize: 13 }
                                Text {
                                    anchors.right: parent.right; y: 2
                                    text: modelData.amount + "  " + Math.round(modelData.pct * 100) + "%"
                                    color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                                }
                                Meter { x: 26; y: 24; width: parent.width - 26; height: 5; value: modelData.pct }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.go("budgets") }
                            }
                        }
                        Empty { visible: fl.d.categories.length === 0; text: "No expenses this month" }
                    }
                    Panel {
                        id: trendP
                        width: (parent.width - 14) / 2
                        title: "Income vs expenses"
                        note: "6 months"
                        Columns { width: parent.width; model: fl.d.trend }
                    }
                }
                Row {
                    width: parent.width; spacing: 14
                    Panel {
                        id: upP
                        width: (parent.width - 14) * 0.56
                        height: Math.max(implicitHeight, cardsP.implicitHeight)
                        title: "Coming up · 30 days"
                        note: fl.d.upcoming.length ? "out " + fl.d.upcomingTotal : ""
                        Repeater {
                            model: fl.d.upcoming
                            Line {
                                glyph: modelData.icon
                                title: modelData.desc
                                sub: modelData.dlabel + "  ·  " + modelData.when + "  ·  " + modelData.sub
                                amount: modelData.amount
                                rightColor: modelData.type === "income" ? Theme.ok : Theme.foreground
                                onClicked: {
                                    if (modelData.kind === "card") { root.filter("card", modelData.id); root.go("cards") }
                                    else if (modelData.kind === "recurring") root.act("rec:edit:" + modelData.id)
                                    else root.act("txn:edit:" + modelData.id)
                                }
                            }
                        }
                        Empty { visible: fl.d.upcoming.length === 0; text: "Nothing scheduled" }
                    }
                    Panel {
                        id: cardsP
                        width: (parent.width - 14) * 0.44
                        title: "Credit cards"
                        Repeater {
                            model: fl.d.cards
                            Item {
                                width: parent.width; height: modelData.ok ? 92 : 48
                                Rectangle { anchors.fill: parent; radius: Theme.radius; color: Theme.tint5; opacity: ccA.containsMouse ? 1 : 0 }
                                Column {
                                    x: 6; y: 6; width: parent.width - 12
                                    spacing: 4
                                    Item {
                                        width: parent.width; height: 20
                                        Label { text: modelData.name; font.bold: true }
                                        Text {
                                            anchors.right: parent.right
                                            text: modelData.ok ? (modelData.settled ? "✓ statement paid" : modelData.left) : modelData.debt
                                            color: modelData.ok && !modelData.settled && modelData.duePast ? Theme.error : modelData.ok && modelData.settled ? Theme.ok : Theme.foreground
                                            font.family: Theme.fontUi; font.pixelSize: 14; font.bold: true
                                        }
                                    }
                                    Text {
                                        visible: modelData.ok
                                        width: parent.width; elide: Text.ElideRight
                                        text: modelData.ok ? (modelData.settled ? `next due ${modelData.nextDue}` : `due ${modelData.lastDue} · ${modelData.dueWhen}`) : ""
                                        color: modelData.ok && !modelData.settled && modelData.duePast ? Theme.error : Theme.muted
                                        font.family: Theme.fontUi; font.pixelSize: 12
                                    }
                                    Meter { visible: modelData.ok; width: parent.width; value: modelData.cyclePct ?? 0 }
                                    Text {
                                        width: parent.width; elide: Text.ElideRight
                                        text: modelData.ok ? `cycle ${modelData.current} · closes ${modelData.nextClose} (${modelData.closeWhen})` : "no closing day: set it in Cards"
                                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                                    }
                                }
                                MouseArea { id: ccA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: { root.filter("card", modelData.id); root.go("cards") } }
                            }
                        }
                        Empty { visible: fl.d.cards.length === 0; text: "No credit cards" }
                    }
                }
                Panel {
                    width: parent.width
                    title: "Recent transactions"
                    note: "see all in Transactions"
                    Repeater {
                        model: fl.d.recent
                        TxnRow { t: modelData; showDate: true; onOpen: root.act("txn:edit:" + modelData.id); onRemove: root.act("txn:del:" + modelData.id) }
                    }
                }
            }
        }
    }

    Component {
        id: vTxns
        Item {
            id: tv
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            readonly property var f: tv.d.filters
            Column {
                id: tbar
                width: parent.width
                spacing: 10
                Row {
                    width: parent.width
                    spacing: 8
                    Rectangle {
                        width: parent.width - accDD.width - catDD.width - 16; height: 32
                        radius: Theme.radius; color: "transparent"
                        border.width: 1; border.color: sBox.activeFocus ? Theme.foreground : Theme.lineStrong
                        Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: "󰍉"; color: Theme.muted; font.family: Theme.fontMono; font.pixelSize: 14 }
                        TextInput {
                            id: sBox
                            anchors { fill: parent; leftMargin: 32; rightMargin: 10 }
                            verticalAlignment: TextInput.AlignVCenter
                            color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13
                            clip: true
                            text: tv.f.q
                            onTextEdited: sDeb.restart()
                            Keys.onEscapePressed: { if (text) { text = ""; sDeb.restart() } else root.forceActiveFocus() }
                            Timer { id: sDeb; interval: 250; onTriggered: root.filter("q", sBox.text) }
                        }
                        Text {
                            anchors.fill: sBox; verticalAlignment: Text.AlignVCenter
                            visible: sBox.text === ""
                            text: "Search description, account, category, note…"
                            color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 13
                        }
                    }
                    Btn {
                        id: accDD
                        glyph: "󰆛"
                        text: (tv.d.accounts.find(o => o.value === String(tv.f.facc)) ?? tv.d.accounts[0]).label
                        onClicked: picker.show("Account", tv.d.accounts, tv.f.facc, v => root.filter("facc", v))
                    }
                    Btn {
                        id: catDD
                        glyph: "󰓹"
                        text: (tv.d.cats.find(o => o.value === String(tv.f.fcat)) ?? tv.d.cats[0]).label
                        onClicked: picker.show("Category", tv.d.cats, tv.f.fcat, v => root.filter("fcat", v))
                    }
                }
                Item {
                    width: parent.width; height: 30
                    Row {
                        spacing: 6
                        Repeater {
                            model: [["", "All"], ["expense", "Expenses"], ["income", "Income"], ["transfer", "Transfers"], ["adjust", "Adjustments"]]
                            Chip { text: modelData[1]; sel: tv.f.ftype === modelData[0]; onClicked: root.filter("ftype", modelData[0]) }
                        }
                    }
                    Text {
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: `${tv.d.count} transactions  ·  in ${tv.d.income}  ·  out ${tv.d.expense}`
                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                    }
                }
                Btn {
                    visible: tv.f.q !== "" || tv.f.ftype !== "" || tv.f.facc !== "" || tv.f.fcat !== ""
                    small: true; glyph: "󰅖"; text: "Clear filters"
                    onClicked: { root.filter("q", ""); root.filter("ftype", ""); root.filter("facc", ""); root.filter("fcat", "") }
                }
            }
            Flickable {
                id: tfl
                anchors { top: tbar.bottom; topMargin: 10; left: parent.left; right: parent.right; bottom: parent.bottom }
                contentHeight: dayCol.implicitHeight + 16
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: dayCol
                    width: tfl.width
                    spacing: 2
                    Repeater {
                        model: tv.d.days
                        Column {
                            width: dayCol.width
                            Item {
                                width: parent.width; height: 34
                                Caps {
                                    anchors.bottom: parent.bottom; anchors.bottomMargin: 6; x: 4
                                    text: modelData.label + (modelData.when ? "  ·  " + modelData.when : "") + (modelData.future ? "  ·  scheduled" : "")
                                    color: modelData.future ? Qt.alpha(Theme.muted, 0.7) : Theme.muted
                                }
                                Text {
                                    anchors { right: parent.right; rightMargin: 34; bottom: parent.bottom; bottomMargin: 6 }
                                    text: modelData.netFmt
                                    color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                                }
                                Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.lineSoft }
                            }
                            Repeater {
                                model: modelData.items
                                TxnRow { t: modelData; onOpen: root.act("txn:edit:" + modelData.id); onRemove: root.act("txn:del:" + modelData.id) }
                            }
                        }
                    }
                    Empty { visible: tv.d.days.length === 0; height: 120; text: "No transactions match" }
                }
            }
        }
    }

    Component {
        id: vBudgets
        Flickable {
            id: bfl
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            contentHeight: bCol.implicitHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: bCol
                width: bfl.width
                spacing: 14
                Panel {
                    width: parent.width
                    Item {
                        width: parent.width; height: 58
                        Column {
                            spacing: 4
                            Caps { text: "Budgeted" }
                            Text { text: bfl.d.total; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 20; font.bold: true }
                        }
                        Column {
                            x: parent.width * 0.34
                            spacing: 4
                            Caps { text: "Spent" }
                            Text { text: bfl.d.spent; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 20; font.bold: true }
                        }
                        Column {
                            x: parent.width * 0.67
                            spacing: 4
                            Caps { text: bfl.d.over ? "Over budget" : "Left to spend" }
                            Text { text: bfl.d.left; color: bfl.d.over ? Theme.error : Theme.ok; font.family: Theme.fontUi; font.pixelSize: 20; font.bold: true }
                        }
                    }
                    Meter { width: parent.width; height: 8; value: bfl.d.pct; mark: bfl.d.pace; tone: bfl.d.over ? "error" : bfl.d.pct > bfl.d.pace + 0.05 && bfl.d.pace > 0 && bfl.d.pace < 1 ? "warn" : "ok" }
                    Text {
                        visible: text !== ""
                        text: bfl.d.paceLabel ? `${bfl.d.paceLabel} · the line marks where spending "should" be` : ""
                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                    }
                }
                Panel {
                    width: parent.width
                    title: "Categories"
                    note: "click to set this month's budget"
                    Repeater {
                        model: bfl.d.rows
                        Item {
                            id: br
                            width: parent.width; height: 62
                            Rectangle { anchors.fill: parent; radius: Theme.radius; color: Theme.tint5; opacity: brH.hovered ? 1 : 0 }
                            HoverHandler { id: brH }
                            MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.act("cat:budget:" + modelData.id) }
                            Badge { id: brB; x: 6; y: 8; glyph: modelData.icon }
                            Item {
                                anchors { left: brB.right; leftMargin: 12; right: parent.right; rightMargin: 8 }
                                y: 8; height: 46
                                Label { width: parent.width * 0.4; text: modelData.name; font.bold: true }
                                Row {
                                    anchors.right: parent.right
                                    spacing: 8
                                    Rectangle {
                                        visible: modelData.override
                                        width: ovT.implicitWidth + 12; height: 18; radius: 9; color: Theme.tint10
                                        Text { id: ovT; anchors.centerIn: parent; text: "this month"; color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 11 }
                                    }
                                    Text {
                                        text: `${modelData.spent} of ${modelData.budget}`
                                        color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                                    }
                                    Text {
                                        text: modelData.status
                                        color: modelData.over ? Theme.error : modelData.tone === "warn" ? Theme.warn : Theme.foreground
                                        font.family: Theme.fontUi; font.pixelSize: 13; font.bold: true
                                    }
                                }
                                Meter { y: 25; width: parent.width; value: modelData.pct; mark: bfl.d.pace; tone: modelData.tone }
                                Text {
                                    y: 35
                                    text: `avg ${modelData.avg} / month (last 3)` + (modelData.override ? ` · default ${modelData.default}` : "")
                                    color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 11
                                }
                                Btn {
                                    anchors.right: parent.right; y: 30
                                    small: true; text: "Default"
                                    opacity: brH.hovered ? 1 : 0
                                    onClicked: root.act("cat:edit:" + modelData.id)
                                }
                            }
                        }
                    }
                    Empty { visible: bfl.d.rows.length === 0; text: "No budgets yet: set one on a category below" }
                }
                Panel {
                    visible: bfl.d.unbudgeted.length > 0
                    width: parent.width
                    title: "Without budget"
                    note: bfl.d.noCategory ? "no category " + bfl.d.noCategory : ""
                    Repeater {
                        model: bfl.d.unbudgeted
                        Line {
                            glyph: modelData.icon
                            title: modelData.name
                            sub: `avg ${modelData.avg} / month (last 3) · click to set a monthly budget`
                            amount: modelData.spent
                            dim: modelData.value <= 0
                            onClicked: root.act("cat:edit:" + modelData.id)
                        }
                    }
                }
                Btn { glyph: "󰐕"; text: "New category"; onClicked: root.act("cat:new") }
            }
        }
    }

    Component {
        id: vCards
        Flickable {
            id: cfl
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            contentHeight: cCol.implicitHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            readonly property var dt: cfl.d.detail
            readonly property var sel: cfl.d.cards.find(c => c.id === cfl.d.selected) ?? null
            Column {
                id: cCol
                width: cfl.width
                spacing: 14
                Row {
                    width: parent.width
                    spacing: 12
                    Repeater {
                        model: cfl.d.cards
                        Rectangle {
                            id: ct
                            readonly property bool sel: modelData.id === cfl.d.selected
                            width: Math.min(270, (cCol.width - 12 * (cfl.d.cards.length)) / (cfl.d.cards.length + 0.6))
                            height: 112
                            radius: Theme.radius + 4
                            color: sel ? Theme.foreground : (ctA.containsMouse ? Theme.tint10 : Theme.tint5)
                            border.width: 1; border.color: sel ? Theme.foreground : Theme.lineSoft
                            Behavior on color { ColorAnimation { duration: Motion.snap } }
                            readonly property color ink: sel ? Theme.background : Theme.foreground
                            readonly property color ink2: sel ? Qt.alpha(Theme.background, 0.7) : Theme.muted
                            Text { x: 16; y: 14; text: "󰆛"; color: ct.ink2; font.family: Theme.fontMono; font.pixelSize: 16 }
                            Text { x: 40; y: 14; width: parent.width - 56; elide: Text.ElideRight; text: modelData.name + (modelData.hidden ? " (hidden)" : ""); color: ct.ink; font.family: Theme.fontUi; font.pixelSize: 14; font.bold: true }
                            Text { x: 16; y: 44; text: modelData.debt; color: ct.ink; font.family: Theme.fontUi; font.pixelSize: 20; font.bold: true }
                            Text { x: 16; y: 72; text: "balance owed"; color: ct.ink2; font.family: Theme.fontUi; font.pixelSize: 11 }
                            Text {
                                anchors { right: parent.right; rightMargin: 16 }
                                y: 72
                                text: modelData.ok ? `closes ${modelData.nextClose}` : "no closing day"
                                color: ct.ink2; font.family: Theme.fontUi; font.pixelSize: 11
                            }
                            Rectangle {
                                visible: modelData.ok
                                x: 16; y: 92; width: parent.width - 32; height: 4; radius: 2
                                color: ct.sel ? Qt.alpha(Theme.background, 0.25) : Theme.tint10
                                Rectangle { width: parent.width * (modelData.cyclePct ?? 0); height: parent.height; radius: 2; color: ct.sel ? Theme.background : Theme.primary }
                            }
                            MouseArea { id: ctA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.filter("card", modelData.id) }
                        }
                    }
                    Rectangle {
                        width: 112; height: 112
                        radius: Theme.radius + 4
                        color: ncA.containsMouse ? Theme.tint10 : "transparent"
                        border.width: 1; border.color: Theme.line
                        Column {
                            anchors.centerIn: parent; spacing: 6
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "󰐕"; color: Theme.inkMuted; font.family: Theme.fontMono; font.pixelSize: 20 }
                            Text { anchors.horizontalCenter: parent.horizontalCenter; text: "New card"; color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 12 }
                        }
                        MouseArea { id: ncA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.act("acc:new:card") }
                    }
                }
                Empty { visible: cfl.d.cards.length === 0; text: "No credit cards yet (an account of type credit card)" }

                Panel {
                    visible: cfl.sel !== null && !cfl.sel.ok
                    width: parent.width
                    title: "Closing day"
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: "This card has no closing day. Set the usual closing and due days to see statements, cycles and what to pay."
                        color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                    }
                    Row {
                        spacing: 8
                        Btn { text: "Set closing day"; onClicked: root.act("acc:edit:" + cfl.sel.id) }
                        Btn { text: "Add a closing date"; onClicked: root.act("card:closing:" + cfl.sel.id) }
                    }
                }

                Row {
                    visible: cfl.sel !== null && cfl.sel.ok
                    width: parent.width
                    spacing: 14
                    Panel {
                        width: (parent.width - 14) / 2
                        height: Math.max(implicitHeight, cycP.implicitHeight)
                        title: "Statement to pay"
                        note: cfl.sel && cfl.sel.ok ? cfl.sel.closedRange : ""
                        Text {
                            text: cfl.sel && cfl.sel.ok ? (cfl.sel.settled ? "✓ Paid" : cfl.sel.left) : ""
                            color: cfl.sel && cfl.sel.ok && cfl.sel.settled ? Theme.ok : cfl.sel && cfl.sel.duePast ? Theme.error : Theme.foreground
                            font.family: Theme.fontUi; font.pixelSize: 26; font.bold: true
                        }
                        Text {
                            text: cfl.sel && cfl.sel.ok ? `due ${cfl.sel.lastDue} · ${cfl.sel.dueWhen}` + (cfl.sel.duePast && !cfl.sel.settled ? " · overdue" : "") : ""
                            color: cfl.sel && cfl.sel.duePast && !cfl.sel.settled ? Theme.error : Theme.muted
                            font.family: Theme.fontUi; font.pixelSize: 13
                        }
                        Item { width: 1; height: 4 }
                        Text {
                            text: cfl.sel && cfl.sel.ok ? `statement ${cfl.sel.closed}  ·  paid ${cfl.sel.paid}` : ""
                            color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                        }
                        Item { width: 1; height: 6 }
                        Row {
                            spacing: 8
                            Btn { primary: true; glyph: "󰄬"; text: "Pay"; onClicked: root.act("card:pay:" + cfl.sel.id) }
                            Btn { text: "Adjust statement"; onClicked: root.act("card:statement:" + cfl.sel.id) }
                            Btn { text: "Set balance"; onClicked: root.act("acc:balance:" + cfl.sel.id) }
                        }
                    }
                    Panel {
                        id: cycP
                        width: (parent.width - 14) / 2
                        title: "Current cycle"
                        note: cfl.sel && cfl.sel.ok ? cfl.sel.cycleRange : ""
                        Text {
                            text: cfl.sel && cfl.sel.ok ? cfl.sel.current : ""
                            color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 26; font.bold: true
                        }
                        Text {
                            text: cfl.sel && cfl.sel.ok ? `closes ${cfl.sel.nextClose} · ${cfl.sel.closeWhen}  ·  due ${cfl.sel.nextDue}` : ""
                            color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 13
                        }
                        Item { width: 1; height: 4 }
                        Meter { width: parent.width; value: cfl.sel && cfl.sel.ok ? cfl.sel.cyclePct : 0 }
                        Text {
                            text: cfl.sel && cfl.sel.ok ? `installments after this cycle: ${cfl.sel.upcoming}` : ""
                            color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                        }
                        Row {
                            spacing: 8
                            Btn { glyph: "󰐕"; text: "Charge"; onClicked: root.act("txn:new:acc:" + cfl.sel.id) }
                            Btn { glyph: "󰃭"; text: "Closing dates"; onClicked: root.act("card:closing:" + cfl.sel.id) }
                            Btn { glyph: "󰏫"; text: "Edit card"; onClicked: root.act("acc:edit:" + cfl.sel.id) }
                        }
                    }
                }

                Panel {
                    visible: cfl.dt !== null && cfl.dt.statements.length > 0
                    width: parent.width
                    title: "Statements"
                    note: "closed · open · coming (installments already loaded)  ·  • = closing date set by hand"
                    Bars {
                        width: parent.width
                        model: cfl.dt ? cfl.dt.statements.map(s => Object.assign({ sub: "due " + s.due }, s)) : []
                    }
                }

                Panel {
                    visible: cfl.dt !== null && cfl.sel && cfl.sel.ok
                    width: parent.width
                    title: "Closing dates"
                    note: cfl.sel ? `usual: closes day ${cfl.sel.closeDay} · due day ${cfl.sel.payDay}` : ""
                    Text {
                        width: parent.width; wrapMode: Text.WordWrap
                        text: "Banks move the closing date every month. Load the real closing and due dates printed on the statement and the cycles, statements and due dates follow them; months without one use the usual day."
                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                    }
                    Flow {
                        width: parent.width
                        spacing: 8
                        Repeater {
                            model: cfl.dt ? cfl.dt.closings : []
                            Rectangle {
                                id: cc
                                width: ccRow.implicitWidth + 20; height: 32
                                radius: Theme.radius
                                color: "transparent"; border.width: 1; border.color: modelData.past ? Theme.lineSoft : Theme.lineStrong
                                Row {
                                    id: ccRow
                                    anchors.centerIn: parent
                                    spacing: 8
                                    Text { text: `closes ${modelData.close} · due ${modelData.due}`; color: modelData.past ? Theme.muted : Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13 }
                                    Text {
                                        text: "󰅖"; color: ccX.containsMouse ? Theme.error : Theme.muted; font.family: Theme.fontMono; font.pixelSize: 13
                                        MouseArea { id: ccX; anchors.fill: parent; anchors.margins: -4; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.act(`card:closedel:${cfl.dt.id}:${modelData.key}`) }
                                    }
                                }
                            }
                        }
                        Btn { small: true; glyph: "󰐕"; text: "Add closing date"; onClicked: root.act("card:closing:" + cfl.dt.id) }
                    }
                }

                Panel {
                    visible: cfl.dt !== null && cfl.sel && cfl.sel.ok
                    width: parent.width
                    title: "This cycle"
                    note: cfl.dt ? `${cfl.dt.cycle.length} charges` + (cfl.dt.payFrom ? ` · paid from ${cfl.dt.payFrom}` : "") : ""
                    Repeater {
                        model: cfl.dt ? cfl.dt.cycle : []
                        TxnRow { t: modelData; showDate: true; onOpen: root.act("txn:edit:" + modelData.id); onRemove: root.act("txn:del:" + modelData.id) }
                    }
                    Empty { visible: cfl.dt && cfl.dt.cycle.length === 0; text: "Nothing in this cycle yet" }
                }
            }
        }
    }

    Component {
        id: vPlans
        Flickable {
            id: pfl
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            contentHeight: pCol.implicitHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: pCol
                width: pfl.width
                spacing: 14
                Row {
                    width: parent.width; spacing: 12
                    Kpi { width: (pCol.width - 36) / 4; label: "Still to pay"; value: pfl.d.pending; sub: `${pfl.d.count} active purchases` }
                    Kpi { width: (pCol.width - 36) / 4; label: "This month"; value: pfl.d.thisMonth; sub: "installments due" }
                    Kpi { width: (pCol.width - 36) / 4; label: "Next month"; value: pfl.d.nextMonth; sub: "already committed" }
                    Kpi { width: (pCol.width - 36) / 4; label: "Finished"; value: String(pfl.d.doneCount); sub: "purchases paid off" }
                }
                Panel {
                    width: parent.width
                    title: "Committed per month"
                    note: "next 12 months"
                    Bars { width: parent.width; barHeight: 100; model: pfl.d.commit.map((c, i) => Object.assign({ state: i === 0 ? "open" : "future" }, c)) }
                }
                Panel {
                    width: parent.width
                    title: "Active"
                    note: "click to see each installment"
                    Repeater {
                        model: pfl.d.active
                        Column {
                            id: pr
                            width: parent.width
                            Item {
                                width: parent.width; height: 64
                                Rectangle { anchors.fill: parent; radius: Theme.radius; color: Theme.tint5; opacity: prH.hovered || modelData.open ? 1 : 0 }
                                HoverHandler { id: prH }
                                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.act("plan:open:" + modelData.id) }
                                Badge { id: prB; x: 6; y: 10; glyph: modelData.icon }
                                Item {
                                    anchors { left: prB.right; leftMargin: 12; right: parent.right; rightMargin: 8 }
                                    y: 9; height: 48
                                    Label { width: parent.width - 260; text: modelData.desc; font.bold: true }
                                    Text {
                                        anchors.right: parent.right
                                        text: modelData.left + " left"
                                        color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 14; font.bold: true
                                    }
                                    Text {
                                        y: 19; width: parent.width - 150; elide: Text.ElideRight
                                        text: `${modelData.each} × ${modelData.n}  ·  ${modelData.acct}  ·  ${modelData.cat}` + (modelData.next ? `  ·  next ${modelData.next}` : "")
                                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                                    }
                                    Text {
                                        anchors.right: parent.right; y: 19
                                        text: `${modelData.paid}/${modelData.n} · ends ${modelData.end}`
                                        color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                                    }
                                    Meter { y: 40; width: parent.width; value: modelData.pct }
                                }
                            }
                            Column {
                                visible: !!modelData.open
                                x: 50; width: parent.width - 50
                                spacing: 0
                                Row {
                                    spacing: 8; topPadding: 6; bottomPadding: 6
                                    Btn { small: true; glyph: "󰏫"; text: "Edit purchase"; onClicked: root.act("plan:edit:" + modelData.id) }
                                    Btn { small: true; danger: true; glyph: "󰆴"; text: "Delete purchase"; onClicked: root.act("plan:del:" + modelData.id) }
                                }
                                Repeater {
                                    model: modelData.items ?? []
                                    Line {
                                        height: 34
                                        title: modelData.no + "   " + modelData.date
                                        amount: modelData.amount
                                        rightSub: ""
                                        dim: !modelData.paid
                                        sub: ""
                                        onClicked: root.act("txn:edit:" + modelData.id)
                                    }
                                }
                            }
                        }
                    }
                    Empty { visible: pfl.d.active.length === 0; text: "No purchases in installments" }
                }
                Panel {
                    visible: pfl.d.done.length > 0
                    width: parent.width
                    title: "Finished"
                    note: pfl.d.doneCount > pfl.d.done.length ? `last ${pfl.d.done.length} of ${pfl.d.doneCount}` : ""
                    Repeater {
                        model: pfl.d.done
                        Line {
                            height: 40
                            glyph: modelData.icon; dim: true
                            title: modelData.desc
                            sub: `${modelData.n} × ${modelData.each} · ${modelData.acct} · ended ${modelData.end}`
                            amount: modelData.total
                            onClicked: root.act("plan:edit:" + modelData.id)
                        }
                    }
                }
                Btn { glyph: "󰐕"; text: "New purchase in installments"; onClicked: root.act("txn:new:inst") }
            }
        }
    }

    Component {
        id: vScheduled
        Flickable {
            id: sfl
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            contentHeight: sCol.implicitHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: sCol
                width: sfl.width
                spacing: 14
                Row {
                    width: parent.width; spacing: 12
                    Kpi { width: (sCol.width - 36) / 4; label: "Fixed out"; value: sfl.d.out; sub: "per month" }
                    Kpi { width: (sCol.width - 36) / 4; label: "Fixed in"; value: sfl.d.in; sub: "per month"; tone: "ok" }
                    Kpi { width: (sCol.width - 36) / 4; label: "Fixed net"; value: sfl.d.net; sub: "what's left after the fixed" }
                    Kpi { width: (sCol.width - 36) / 4; label: "Active"; value: String(sfl.d.active); sub: `of ${sfl.d.rows.length} scheduled` }
                }
                Row {
                    width: parent.width; spacing: 14
                    Panel {
                        width: (parent.width - 14) * 0.58
                        height: Math.max(implicitHeight, nextP.implicitHeight)
                        title: "Scheduled"
                        note: "posted on their date"
                        Repeater {
                            model: sfl.d.rows
                            Item {
                                width: parent.width; height: 50
                                Line {
                                    anchors.fill: parent
                                    glyph: modelData.icon
                                    dim: !modelData.active
                                    title: modelData.desc
                                    sub: [modelData.freq, modelData.acct, modelData.cat, modelData.ends ? "until " + modelData.ends : ""].filter(x => x).join("  ·  ")
                                    amount: modelData.amount
                                    rightSub: modelData.active ? `${modelData.next} · ${modelData.when}` : "paused"
                                    rightColor: modelData.type === "income" ? Theme.ok : Theme.foreground
                                    onClicked: root.act("rec:edit:" + modelData.id)
                                }
                                Row {
                                    anchors { right: parent.right; rightMargin: 160; verticalCenter: parent.verticalCenter }
                                    spacing: 6
                                    opacity: rH.hovered ? 1 : 0
                                    Btn { small: true; text: modelData.active ? "Pause" : "Resume"; onClicked: root.act("rec:toggle:" + modelData.id) }
                                    Btn { small: true; danger: true; glyph: "󰆴"; onClicked: root.act("rec:del:" + modelData.id) }
                                }
                                HoverHandler { id: rH }
                            }
                        }
                        Empty { visible: sfl.d.rows.length === 0; text: "Nothing scheduled: rent, salary, subscriptions…" }
                    }
                    Panel {
                        id: nextP
                        width: (parent.width - 14) * 0.42
                        title: "Next 30 days"
                        Repeater {
                            model: sfl.d.upcoming
                            Item {
                                width: parent.width; height: 42
                                Column {
                                    width: 52
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text { text: modelData.dlabel; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13; font.bold: true }
                                    Text { text: modelData.when; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 10 }
                                }
                                Label { x: 70; width: parent.width - 70 - upA.width - 8; anchors.verticalCenter: parent.verticalCenter; text: modelData.desc; font.pixelSize: 13 }
                                Text {
                                    id: upA
                                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                                    text: modelData.amount
                                    color: modelData.type === "income" ? Theme.ok : Theme.foreground
                                    font.family: Theme.fontUi; font.pixelSize: 13
                                }
                            }
                        }
                        Empty { visible: sfl.d.upcoming.length === 0; text: "Nothing in the next 30 days" }
                    }
                }
                Row {
                    spacing: 8
                    Btn { glyph: "󰐕"; text: "New scheduled"; onClicked: root.act("rec:new") }
                    Btn { glyph: "󰑐"; text: "Post due now"; onClicked: root.act("rec:post") }
                }
            }
        }
    }

    Component {
        id: vReports
        Flickable {
            id: rfl
            property var d: ({})               // datos de esta vista (los pone present())
            property string viewKey: ""
            anchors.fill: parent
            contentHeight: rCol.implicitHeight + 16
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Column {
                id: rCol
                width: rfl.width
                spacing: 14
                Row {
                    width: parent.width; spacing: 12
                    Kpi { width: (rCol.width - 36) / 4; label: "Income · " + rfl.d.year.span; value: rfl.d.year.income; sub: "up to " + (root.info ? root.info.monthLabel : "") }
                    Kpi { width: (rCol.width - 36) / 4; label: "Expenses · " + rfl.d.year.span; value: rfl.d.year.expense; sub: `avg ${rfl.d.year.avgExp} / month` }
                    Kpi { width: (rCol.width - 36) / 4; label: "Net · " + rfl.d.year.span; value: rfl.d.year.net; sub: "income − expenses" }
                    Kpi { width: (rCol.width - 36) / 4; label: "Savings rate"; value: rfl.d.year.rate; sub: "of income kept" }
                }
                Panel {
                    width: parent.width
                    title: "Income vs expenses"
                    note: rfl.d.year.span
                    Columns {
                        width: parent.width; height: 220
                        normalized: true
                        model: rfl.d.trend
                    }
                }
                Row {
                    width: parent.width; spacing: 14
                    Panel {
                        width: (parent.width - 14) * 0.58
                        height: Math.max(implicitHeight, accP.implicitHeight)
                        title: "Categories vs 3-month average"
                        note: root.info ? root.info.monthLabel : ""
                        Repeater {
                            model: rfl.d.comp
                            Item {
                                width: parent.width; height: 42
                                Text { y: 1; text: modelData.icon; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13 }
                                Label { x: 24; y: 1; width: parent.width * 0.45; text: modelData.name; font.pixelSize: 13 }
                                Text {
                                    anchors.right: parent.right; y: 1
                                    text: `${modelData.nowFmt}  ·  avg ${modelData.avgFmt}  ·  ${modelData.delta}`
                                    color: modelData.up ? Theme.foreground : Theme.muted
                                    font.family: Theme.fontUi; font.pixelSize: 12
                                }
                                Rectangle { x: 24; y: 22; height: 6; radius: 3; width: Math.max(2, modelData.now * (parent.width - 24)); color: Theme.primary }
                                Rectangle { x: 24; y: 31; height: 4; radius: 2; width: Math.max(2, modelData.avg * (parent.width - 24)); color: Qt.alpha(Theme.foreground, 0.32) }
                            }
                        }
                        Empty { visible: rfl.d.comp.length === 0; text: "No expenses" }
                    }
                    Panel {
                        id: accP
                        width: (parent.width - 14) * 0.42
                        title: "Spent by account"
                        Repeater {
                            model: rfl.d.byAccount
                            Item {
                                width: parent.width; height: 34
                                Label { width: parent.width - 80; text: modelData.name; font.pixelSize: 13 }
                                Text { anchors.right: parent.right; text: modelData.amount; color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13 }
                                Meter { y: 22; width: parent.width; height: 5; value: modelData.h }
                            }
                        }
                        Empty { visible: rfl.d.byAccount.length === 0; text: "No expenses" }
                    }
                }
                Panel {
                    width: parent.width
                    title: "Largest expenses"
                    note: root.info ? root.info.monthLabel : ""
                    Repeater {
                        model: rfl.d.top
                        TxnRow { t: modelData; showDate: true; onOpen: root.act("txn:edit:" + modelData.id); onRemove: root.act("txn:del:" + modelData.id) }
                    }
                    Empty { visible: rfl.d.top.length === 0; text: "No expenses" }
                }
            }
        }
    }

    // ── selector (cuenta / categoría de los filtros) ────
    Rectangle {
        id: picker
        anchors.fill: parent
        visible: false
        color: Qt.alpha(Theme.background, 0.82)
        property string title: ""
        property var options: []
        property string current: ""
        property var cb: null
        function show(t, opts, cur, f) { title = t; options = opts; current = cur; cb = f; visible = true; pickFlick.contentY = 0; forceActiveFocus() }
        function pick(v) { visible = false; if (cb) cb(v); root.forceActiveFocus() }
        Keys.onEscapePressed: { visible = false; root.forceActiveFocus() }
        MouseArea { anchors.fill: parent; onClicked: { picker.visible = false; root.forceActiveFocus() } }
        Rectangle {
            anchors.centerIn: parent
            width: 380; height: Math.min(pickCol.implicitHeight + 64, parent.height - 60)
            radius: Theme.radius + 2
            color: Theme.surface0
            border.width: 1; border.color: Theme.line
            MouseArea { anchors.fill: parent }
            Text { x: 18; y: 16; text: picker.title; color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 15; font.bold: true }
            Flickable {
                id: pickFlick
                x: 10; y: 48; width: parent.width - 20; height: parent.height - 58
                clip: true
                contentHeight: pickCol.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: pickCol
                    width: parent.width
                    Repeater {
                        model: picker.options
                        Rectangle {
                            readonly property bool sel: modelData.value === picker.current
                            width: pickCol.width; height: 34
                            radius: Theme.radius
                            color: sel ? Theme.foreground : (pkA.containsMouse ? Theme.tint10 : "transparent")
                            Text { x: 10; anchors.verticalCenter: parent.verticalCenter; text: modelData.label; color: parent.sel ? Theme.background : Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 13 }
                            MouseArea { id: pkA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: picker.pick(modelData.value) }
                        }
                    }
                }
            }
        }
    }

    FormLayer {
        id: forms
        anchors.fill: parent
        onSubmitted: (key, text) => root.act(key, text)
        onOpenChanged: if (!open) root.forceActiveFocus()
    }
}
