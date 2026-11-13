pragma ComponentBehavior: Bound
import QtQuick

// Diálogos de una página de la GUI: formulario (varios campos con validación en el lugar),
// pedido de un valor, confirmación y visor de texto largo. Lo usan SectionPage y Finance.
// El backend los pide en el resultado de una acción (ask / text, ver sections/_lib.py); al
// aceptar emite submitted(key, text) y la página llama act(key, text).
Item {
    id: dlg
    property var asking: null                     // {key, title, fields | label, confirm, error, hint, message}
    property var viewer: null                     // {title, body}
    signal submitted(string key, string text)
    readonly property bool open: asking !== null || viewer !== null

    // ── pedido de datos: ask (un campo, act recibe el texto) o form (varios campos, act recibe JSON) ──
    property var vals: ({})
    readonly property var askFields: asking ? (asking.confirm ? [] : asking.fields ?? [{ name: "value", label: asking.label, text: asking.text ?? "", secret: !!asking.secret }]) : []
    onAskingChanged: {
        const v = {}
        if (asking) {
            const fs = asking.fields ?? [{ name: "value", text: asking.text ?? "" }]
            for (const f of fs) v[f.name] = f.text ?? (f.choices && f.choices.length ? dlg.choiceValue(f.choices[0]) : "")
        }
        vals = v
    }
    // Un par [etiqueta, valor] llega a los delegados como lista de Qt (Array.isArray da false)
    function isPair(c) { return c !== null && typeof c === "object" && c.length === 2 }
    function choiceValue(c) { return isPair(c) ? c[1] : c }
    function choiceLabel(c) { return isPair(c) ? c[0] : c }
    function setVal(name, value) { const v = Object.assign({}, vals); v[name] = value; vals = v }

    Rectangle {
        id: askLayer
        anchors.fill: parent
        visible: dlg.asking !== null
        color: Qt.alpha(Theme.background, 0.82)
        MouseArea { anchors.fill: parent }
        Rectangle {
            id: askCard
            anchors.centerIn: parent
            width: Math.min(560, dlg.width - 24)
            height: Math.min(askCol.implicitHeight + 36, dlg.height - 24)
            radius: Theme.radius + 2
            color: Theme.surface0
            border.width: 1; border.color: Theme.line

            Flickable {
              id: askFlick
              anchors.fill: parent
              anchors.margins: 1
              clip: true
              contentHeight: askCol.implicitHeight + 34
              boundsBehavior: Flickable.StopAtBounds
              Column {
                id: askCol
                x: 19; y: 17
                width: askFlick.width - 38
                spacing: 12
                Text {
                    text: dlg.asking ? (dlg.asking.title ?? dlg.asking.label ?? "") : ""
                    color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 15; font.bold: true
                }
                Text {
                    visible: !!(dlg.asking && dlg.asking.error)
                    width: parent.width; wrapMode: Text.WordWrap
                    text: dlg.asking && dlg.asking.error ? "✗ " + dlg.asking.error : ""
                    color: Theme.error; font.family: Theme.fontUi; font.pixelSize: 13
                }
                Repeater {
                    model: dlg.askFields
                    delegate: Column {
                        id: fld
                        required property var modelData
                        required property int index
                        width: askCol.width
                        spacing: 5
                        Text {
                            visible: dlg.askFields.length > 1
                            text: fld.modelData.label
                            color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 11; font.letterSpacing: 1
                        }
                        Rectangle {
                            visible: !fld.modelData.choices
                            width: parent.width; height: 38
                            radius: Theme.radius; color: "transparent"; border.width: 1
                            border.color: inp.activeFocus ? Theme.foreground : Theme.lineStrong
                            Behavior on border.color { ColorAnimation { duration: Motion.snap } }
                            TextInput {
                                id: inp
                                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                                verticalAlignment: TextInput.AlignVCenter
                                color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 14
                                echoMode: fld.modelData.secret ? TextInput.Password : TextInput.Normal
                                clip: true
                                text: fld.modelData.text ?? ""
                                onTextChanged: if (fld.modelData.choices === undefined) dlg.setVal(fld.modelData.name, text)
                                Component.onCompleted: if (fld.index === 0 && !fld.modelData.choices) { forceActiveFocus(); selectAll() }
                                activeFocusOnTab: true
                                Keys.onEscapePressed: dlg.asking = null
                                Keys.onReturnPressed: dlg.submitAsk()
                            }
                        }
                        Flow {
                            visible: !!fld.modelData.choices
                            width: parent.width
                            spacing: 6
                            Repeater {
                                model: fld.modelData.choices ?? []
                                delegate: Rectangle {
                                    id: chip
                                    required property var modelData
                                    readonly property string cv: dlg.choiceValue(modelData)
                                    readonly property bool sel: dlg.vals[fld.modelData.name] === cv
                                    height: 30; width: chipT.implicitWidth + 24
                                    radius: Theme.radius
                                    color: sel ? Theme.foreground : "transparent"
                                    border.width: 1; border.color: sel ? Theme.foreground : Theme.lineStrong
                                    Behavior on color { ColorAnimation { duration: Motion.snap } }
                                    Text {
                                        id: chipT; anchors.centerIn: parent; text: dlg.choiceLabel(chip.modelData)
                                        color: chip.sel ? Theme.background : Theme.foreground
                                        font.family: Theme.fontUi; font.pixelSize: 13
                                    }
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: dlg.setVal(fld.modelData.name, chip.cv) }
                                }
                            }
                        }
                    }
                }
                Text {
                    visible: !!(dlg.asking && dlg.asking.hint)
                    width: parent.width; wrapMode: Text.WordWrap
                    text: dlg.asking && dlg.asking.hint ? dlg.asking.hint : ""
                    color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
                }
                Text {
                    visible: !!(dlg.asking && dlg.asking.message)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: dlg.asking && dlg.asking.message ? dlg.asking.message : ""
                    color: Theme.inkMuted; font.family: Theme.fontUi; font.pixelSize: 13
                }
                Item {
                    width: parent.width; height: 32
                    Text { anchors.verticalCenter: parent.verticalCenter; text: "enter to confirm · esc to cancel"; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12 }
                    Row {
                        anchors.right: parent.right
                        spacing: 8
                        Repeater {
                            model: [{ k: "cancel", t: "Cancel" }, { k: "ok", t: dlg.asking && dlg.asking.okLabel ? dlg.asking.okLabel : (dlg.asking && dlg.asking.confirm ? "Confirm" : "Save") }]
                            delegate: Rectangle {
                                id: mb
                                required property var modelData
                                readonly property bool primary: modelData.k === "ok"
                                readonly property bool danger: primary && !!(dlg.asking && dlg.asking.danger)
                                height: 30; width: mbT.implicitWidth + 26
                                radius: Theme.radius
                                color: mbA.containsMouse ? (danger ? Theme.error : Theme.foreground) : "transparent"
                                border.width: 1; border.color: danger ? Theme.error : (primary ? Theme.foreground : Theme.lineStrong)
                                Behavior on color { ColorAnimation { duration: Motion.snap } }
                                Text {
                                    id: mbT; anchors.centerIn: parent; text: mb.modelData.t
                                    color: mbA.containsMouse ? Theme.background : (mb.danger ? Theme.error : Theme.foreground)
                                    font.family: Theme.fontUi; font.pixelSize: 13
                                }
                                MouseArea {
                                    id: mbA; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor
                                    onClicked: mb.primary ? dlg.submitAsk() : (dlg.asking = null)
                                }
                            }
                        }
                    }
                }
            }
            }
        }
        focus: visible && dlg.askFields.length === 0
        onVisibleChanged: if (visible && dlg.askFields.length === 0) forceActiveFocus()
        Keys.onEscapePressed: dlg.asking = null
        Keys.onReturnPressed: dlg.submitAsk()
    }
    // ── texto largo (diffs, logs, salida de comandos) ──
    Rectangle {
        anchors.fill: parent
        visible: dlg.viewer !== null
        color: Qt.alpha(Theme.background, 0.88)
        MouseArea { anchors.fill: parent; onClicked: dlg.viewer = null }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width - 40; height: parent.height - 40
            radius: Theme.radius + 2
            color: Theme.surface0
            border.width: 1; border.color: Theme.line
            MouseArea { anchors.fill: parent }
            Text {
                id: vT; x: 20; y: 16
                text: dlg.viewer ? (dlg.viewer.title ?? "") : ""
                color: Theme.foreground; font.family: Theme.fontUi; font.pixelSize: 15; font.bold: true
            }
            Text {
                anchors { right: parent.right; rightMargin: 20; verticalCenter: vT.verticalCenter }
                text: "esc to close"; color: Theme.muted; font.family: Theme.fontUi; font.pixelSize: 12
            }
            Flickable {
                id: vF
                x: 20; y: 48; width: parent.width - 40; height: parent.height - 64
                clip: true
                contentWidth: width; contentHeight: vBody.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                focus: dlg.viewer !== null
                Keys.onEscapePressed: dlg.viewer = null
                onVisibleChanged: if (visible) { contentY = 0; forceActiveFocus() }
                TextEdit {
                    id: vBody
                    width: vF.width
                    readOnly: true; selectByMouse: true
                    wrapMode: TextEdit.WrapAnywhere
                    text: dlg.viewer ? (dlg.viewer.body ?? "") : ""
                    color: Theme.foreground; font.family: Theme.fontMono; font.pixelSize: 12
                }
            }
        }
    }

    function submitAsk() {
        if (!asking) return
        const a = asking
        const v = vals
        asking = null
        if (a.confirm) submitted(a.key, "yes")
        else if (a.fields) submitted(a.key, JSON.stringify(v))
        else submitted(a.key, v["value"] ?? "")
    }
}
