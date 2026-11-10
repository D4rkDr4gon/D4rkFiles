pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io

// Backend único de toda la GUI: UN proceso `bridge.py serve` compartido por Settings,
// Gastos, VPN y las demás ventanas. Así los módulos quedan importados una sola vez y el
// helper root (tools/gui/rootd.py, autorizado con la huella vía pkexec) se pide UNA
// vez por apertura de la GUI y se reusa en todas las ventanas.
// Vive mientras haya alguna ventana abierta (acquire/release) y unos minutos de gracia
// después; al morir se lleva al helper root (su stdin se cierra).
Singleton {
    id: b

    readonly property string bridge: Quickshell.env("HOME") + "/.local/share/dotfiles" + "/tools/gui/bridge.py"
    property int users: 0
    property int seq: 0
    property var pending: ({})          // id → callback(res)
    property var outbox: []             // pedidos hechos antes de que el proceso arranque
    // pkexec esperando la huella: las ventanas se ocultan para no tapar el diálogo de polkit
    property bool authorizing: false
    signal event(var ev)                // avisos sin pedido (progreso de trabajos largos)

    function acquire() {
        users += 1
        grace.stop()
        if (!srv.running) srv.running = true
    }
    function release() {
        users = Math.max(0, users - 1)
        if (users === 0) grace.restart()
    }

    function request(section, op, args, cb) {
        seq += 1
        const id = "q" + seq
        pending[id] = cb
        const line = JSON.stringify({ id: id, section: section, op: op, args: args }) + "\n"
        if (srv.running) srv.write(line)
        else { outbox.push(line); srv.running = true }
        return id
    }

    function onLine(line) {
        let m
        try { m = JSON.parse(line) } catch (e) { return }
        if (m.event) {
            if (m.event.auth !== undefined) authorizing = !!m.event.auth
            event(m.event)
            return
        }
        const cb = pending[m.id]
        delete pending[m.id]
        if (cb) cb(m.res, m.section)
    }

    function failAll() {
        const p = pending
        pending = ({})
        for (const id in p) { try { p[id]({ ok: false, msg: "Backend restarted" }, "") } catch (e) {} }
    }

    Process {
        id: srv
        command: ["python3", b.bridge, "serve"]
        stdinEnabled: true
        stdout: SplitParser { onRead: line => b.onLine(line) }
        onRunningChanged: {
            if (running) {
                const o = b.outbox
                b.outbox = []
                for (const l of o) srv.write(l)
            } else {
                b.authorizing = false
                b.failAll()
                if (b.users > 0) restart.start()
            }
        }
    }
    Timer { id: restart; interval: 800; onTriggered: if (b.users > 0) srv.running = true }
    // 3 min sin ventanas abiertas: se cierra (y con él el helper root)
    Timer { id: grace; interval: 180000; onTriggered: if (b.users === 0) srv.running = false }
}
