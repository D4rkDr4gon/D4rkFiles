pragma ComponentBehavior: Bound
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland

// Ventana suelta de una herramienta: hospeda la SectionPage de un módulo de
// tools/gui/sections/. Una instancia por herramienta en shell.qml. Dos formas:
//   - tarjeta centrada con velo (`qs ipc call <target> toggle`): atajos de teclado;
//   - cajón que sale de la barra (`qs ipc call <target> drop <x|right> <alto de la barra>`):
//     clic en un módulo de waybar (float-tui-launch.sh → gui-dispatch.sh --drawer). Como en
//     Caelestia: mismo color que la barra, pegado a su borde de abajo con esquinas cóncavas
//     que lo unen, crece hacia abajo con el contenido deslizándose detrás del borde. Hay uno
//     solo abierto a la vez (Drawers.open) y la barra sigue recibiendo clicks.
Scope {
    id: root

    property string target: ""
    property string section: ""
    property string heading: ""
    property string page: ""                // "" = SectionPage genérica; "finance" = Finance.qml (app propia)
    property int cardWidth: 760
    property int cardHeight: 640
    property bool shown: false
    property bool drawer: false             // forma de la apertura actual
    property string dropAt: "right"         // x del clic en el monitor, o "right"
    property int barHeight: 28
    property bool loaded: false             // la página se arma la primera vez y después queda viva
    property real grow: 0                   // 0 → 1: cuánto se extendió el cajón desde la barra

    readonly property string bridge: Quickshell.env("HOME") + "/.local/share/dotfiles" + "/tools/gui/bridge.py"
    readonly property bool animating: card.opacity > 0.01 || grow > 0.001

    onShownChanged: {
        if (shown) loaded = true
        if (!drawer) return
        growOpen.stop(); growClose.stop()
        if (shown) growOpen.start(); else growClose.start()
    }

    // Curvas "emphasized" de Material 3 (familia de las de Caelestia): abrir reparte el
    // movimiento y frena muy suave al final (~510 ms); cerrar acelera y se va (~260 ms). Escalan con el preset de animaciones (Motion).
    NumberAnimation {
        id: growOpen
        target: root; property: "grow"; to: 1
        duration: Math.round(Motion.slow * 1.6)
        easing.type: Easing.BezierSpline
        easing.bezierCurve: [0.2, 0.0, 0.0, 1.0, 1.0, 1.0]
    }
    NumberAnimation {
        id: growClose
        target: root; property: "grow"; to: 0
        duration: Math.round(Motion.swap * 1.25)
        easing.type: Easing.BezierSpline
        easing.bezierCurve: [0.3, 0.0, 0.8, 0.15, 1.0, 1.0]
    }

    function toggle() {
        if (shown) { close(); return }
        if (!animating) drawer = false
        shown = true
    }
    function drop(at, bar) {
        if (shown) { close(); return }
        if (!animating) { drawer = true; dropAt = at; barHeight = bar > 0 ? bar : 28 }
        Drawers.open = target
        shown = true
    }
    function close() {
        shown = false
        if (Drawers.open === target) Drawers.open = ""
    }

    // Abrir otro cajón cierra este
    Connections {
        target: Drawers
        function onOpenChanged() { if (root.shown && root.drawer && Drawers.open !== root.target) root.close() }
    }

    IpcHandler {
        target: root.target
        function toggle(): void { root.toggle() }
        function drop(at: string, bar: int): void { root.drop(at, bar) }
        function act(key: string): void { if (page.item) page.item.act(key) }   // pruebas y atajos: ejecuta una acción de la página
    }

    PanelWindow {
        id: win
        screen: Quickshell.screens.find(s => s.name === Hyprland.focusedMonitor?.name) ?? Quickshell.screens[0]
        // Oculta mientras pkexec pide la huella (si no, la capa overlay tapa el diálogo de polkit)
        visible: (root.shown || root.animating) && !Backend.authorizing
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; left: true; right: true; bottom: true }
        // Cajón: la ventana empieza debajo de la barra, así sus módulos siguen clickeables
        margins.top: root.drawer ? root.barHeight : 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "dotfiles-settings"
        WlrLayershell.keyboardFocus: root.shown ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

        // Velo (en el cajón no oscurece, pero un click afuera igual lo cierra)
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.drawer ? 0 : 0.35)
            opacity: root.shown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
            MouseArea { anchors.fill: parent; onClicked: root.close() }
        }

        FocusScope {
            id: scope
            anchors.fill: parent
            focus: true
            Keys.onPressed: event => { if (event.key === Qt.Key_Escape) { root.close(); event.accepted = true } }
            Connections { target: root; function onShownChanged() { if (root.shown) scope.forceActiveFocus() } }
            Connections { target: Backend; function onAuthorizingChanged() { if (!Backend.authorizing && root.shown) scope.forceActiveFocus() } }

            // ── tarjeta centrada ──
            Rectangle {
                id: card
                visible: !root.drawer
                width: Math.min(root.cardWidth, parent.width - 80)
                height: Math.min(root.cardHeight, parent.height - 80)
                anchors.centerIn: parent
                anchors.verticalCenterOffset: root.shown ? 0 : 14
                radius: Theme.radius + 2
                color: Qt.alpha(Theme.background, Math.max(Theme.opacity, 0.92))
                border.width: 1
                border.color: Theme.line
                opacity: root.shown && !root.drawer ? 1 : 0
                scale: root.shown ? 1 : 0.985
                clip: true

                Behavior on opacity { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
                Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }
                Behavior on scale { NumberAnimation { duration: Motion.swap; easing.type: Motion.out } }

                MouseArea { anchors.fill: parent }
                Item { id: cardSlot; x: 32; y: 20; width: parent.width - 64; height: parent.height - 36 }
            }

            // ── cajón de la barra ──
            // La barra "se extiende": arranca como una lengüeta angosta bajo el módulo y se
            // ensancha y estira a la vez (grow), con las esquinas cóncavas viajando con los bordes.
            Item {
                id: box
                visible: root.drawer && root.grow > 0.001
                readonly property int fullW: Math.min(root.cardWidth, parent.width - 24)
                readonly property int fullH: Math.min(root.cardHeight, parent.height - 16)
                readonly property int startW: 96
                readonly property int fillet: 16
                readonly property real rad: Math.min(Math.max(Theme.radius + 10, 14), height / 2)
                readonly property color fill: Qt.alpha(Theme.background, 0.97)   // = fondo de waybar (theme.css)
                readonly property real at: root.dropAt === "right" ? -1 : Number(root.dropAt)
                // centro final (contenido a la vista) y el de partida (bajo el clic)
                readonly property real endX: at < 0 ? parent.width - fullW - 12 : Math.max(12, Math.min(parent.width - fullW - 12, at - fullW / 2))
                readonly property real endC: endX + fullW / 2
                readonly property real startC: at < 0 ? parent.width - 12 - startW / 2 : Math.max(12 + startW / 2, Math.min(parent.width - 12 - startW / 2, at))
                readonly property real c: startC + (endC - startC) * root.grow

                width: startW + (fullW - startW) * root.grow
                height: fullH * root.grow
                x: c - width / 2
                y: 0

                // Esquinas cóncavas que unen el cajón con el borde de la barra
                Repeater {
                    model: [-1, 1]
                    Canvas {
                        id: fil
                        required property int modelData
                        readonly property real f: Math.min(box.fillet, box.height)
                        x: modelData < 0 ? -box.fillet : box.width
                        width: box.fillet; height: box.fillet
                        onFChanged: requestPaint()
                        Connections { target: Theme; function onBackgroundChanged() { fil.requestPaint() } }
                        onPaint: {
                            const ctx = getContext("2d")
                            ctx.reset()
                            const s = f, w = width
                            if (s < 1) return
                            ctx.fillStyle = box.fill
                            ctx.beginPath()
                            if (modelData < 0) {           // a la izquierda: curva hacia el lado izquierdo del cajón
                                ctx.moveTo(w - s, 0); ctx.lineTo(w, 0); ctx.lineTo(w, s)
                                ctx.arc(w - s, s, s, 0, -Math.PI / 2, true)
                            } else {
                                ctx.moveTo(0, 0); ctx.lineTo(s, 0)
                                ctx.arc(s, s, s, -Math.PI / 2, Math.PI, true)
                                ctx.lineTo(0, 0)
                            }
                            ctx.closePath()
                            ctx.fill()
                        }
                    }
                }

                Item {
                    anchors.fill: parent
                    clip: true
                    // Arriba recto (pegado a la barra), abajo redondeado
                    Rectangle {
                        y: -box.rad
                        width: parent.width
                        height: parent.height + box.rad
                        radius: box.rad
                        color: box.fill
                    }
                    MouseArea { anchors.fill: parent }
                    // El contenido queda quieto en su lugar final y el cajón lo va descubriendo;
                    // aparece cuando la forma ya creció (y al cerrar se va primero)
                    Item {
                        id: drawerSlot
                        x: box.endX - box.x + 28
                        y: 16 - (1 - root.grow) * 10
                        width: box.fullW - 56
                        height: box.fullH - 34
                        opacity: Math.max(0, Math.min(1, (root.grow - 0.45) / 0.45))
                    }
                }
            }

            Loader {
                id: page
                focus: true                         // Finance toma el teclado (1-8, ←/→, n)
                parent: root.drawer ? drawerSlot : cardSlot
                anchors.fill: parent
                active: root.loaded
                asynchronous: true                  // se arma sin trabar la animación
                sourceComponent: root.page === "finance" ? financePage : sectionPage
            }
            Component {
                id: sectionPage
                SectionPage {
                    bridge: root.bridge
                    section: root.section
                    active: root.shown
                    standalone: true
                    onCloseRequested: root.close()
                }
            }
            Component {
                id: financePage
                Finance {
                    active: root.shown
                    onCloseRequested: root.close()
                }
            }
        }
    }
}
