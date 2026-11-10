pragma Singleton
import QtQuick

// Movimiento único de toda la GUI (valores tomados de Ryoku: snap 90, move 170,
// swap 210, OutCubic). Ninguna animación define su propia duración. Escala con
// el preset `animations` del tema (smooth | snappy | bouncy | off): "off" = 0.
QtObject {
    readonly property string preset: Theme.motion
    readonly property real k: preset === "off" ? 0 : preset === "snappy" ? 0.7 : preset === "bouncy" ? 1.15 : 1

    readonly property int snap: Math.round(90 * k)       // hover, press, colores
    readonly property int move: Math.round(170 * k)      // la pastilla/selección que viaja
    readonly property int swap: Math.round(210 * k)      // cambio de contenido
    readonly property int slow: Math.round(320 * k)      // temas, aparición de ventanas
    // alias que ya usan los componentes
    readonly property int fast: snap
    readonly property int normal: move

    readonly property int out: Easing.OutCubic
    readonly property int inOut: Easing.InOutCubic
    readonly property int bezier: Easing.BezierSpline
    // curva "spatial" de Ryoku: sobrepasa un poco y se asienta
    readonly property var spatial: [0.38, 1.21, 0.22, 1, 1, 1]
    readonly property int pop: Easing.OutBack
    readonly property real overshoot: preset === "bouncy" ? 2.0 : 1.0
}
