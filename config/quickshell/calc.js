.pragma library

// Calculadora del lanzador: el mismo cálculo que calc() de tools/launcher_tui.py, sin eval.
// Gramática y precedencia de Python: ** (derecha, antes que el signo: -2**2 = -4) > signo > * / // % > + -.
// Acepta x y ^ como operadores y coma decimal. Devuelve el texto del resultado, o null si no es una cuenta.

const NAMES = { pi: Math.PI, e: Math.E, tau: 2 * Math.PI }

function factorial(n) {
    if (!Number.isInteger(n) || n < 0) throw new Error("bad factorial")
    if (n > 500) throw new Error("too big")
    let r = 1
    for (let i = 2; i <= n; i++) r *= i
    return r
}
function pyRound(x, nd) {
    // round() de Python: al par en el empate
    const k = Math.pow(10, nd || 0), v = x * k, f = Math.floor(v), d = v - f
    const r = d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1)
    return r / k
}
const FUNCS = {
    sqrt: x => { if (x < 0) throw new Error("domain"); return Math.sqrt(x) },
    sin: Math.sin, cos: Math.cos, tan: Math.tan,
    log: (x, b) => { if (x <= 0) throw new Error("domain"); return b === undefined ? Math.log(x) : Math.log(x) / Math.log(b) },
    log10: x => { if (x <= 0) throw new Error("domain"); return Math.log10(x) },
    log2: x => { if (x <= 0) throw new Error("domain"); return Math.log2(x) },
    exp: Math.exp, floor: Math.floor, ceil: Math.ceil, factorial: factorial,
    radians: x => x * Math.PI / 180, degrees: x => x * 180 / Math.PI,
    abs: Math.abs, round: pyRound
}

function tokenize(s) {
    const out = []
    let i = 0
    while (i < s.length) {
        const c = s[i]
        if (c === " " || c === "\t") { i++; continue }
        const num = /^(\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)/.exec(s.slice(i))
        if (num) { out.push({ t: "num", v: parseFloat(num[1]) }); i += num[1].length; continue }
        const id = /^[a-z_][a-z0-9_]*/i.exec(s.slice(i))
        if (id) { out.push({ t: "id", v: id[0] }); i += id[0].length; continue }
        if (s.startsWith("**", i) || s.startsWith("//", i)) { out.push({ t: "op", v: s.substr(i, 2) }); i += 2; continue }
        if ("+-*/%(),".includes(c)) { out.push({ t: "op", v: c }); i++; continue }
        throw new Error("bad char")
    }
    return out
}

function parse(tokens) {
    let p = 0
    const peek = () => tokens[p], take = () => tokens[p++]
    const isOp = v => peek() && peek().t === "op" && peek().v === v
    function expr() {                       // + -
        let a = term()
        while (isOp("+") || isOp("-")) { const o = take().v, b = term(); a = o === "+" ? a + b : a - b }
        return a
    }
    function term() {                       // * / // %
        let a = unary()
        while (isOp("*") || isOp("/") || isOp("//") || isOp("%")) {
            const o = take().v, b = unary()
            if ((o === "/" || o === "//" || o === "%") && b === 0) throw new Error("div by zero")
            a = o === "*" ? a * b : o === "/" ? a / b : o === "//" ? Math.floor(a / b) : a - b * Math.floor(a / b)
        }
        return a
    }
    function unary() {                      // signo (más débil que **)
        if (isOp("-")) { take(); return -unary() }
        if (isOp("+")) { take(); return +unary() }
        return power()
    }
    function power() {                      // ** asocia a la derecha y su exponente puede llevar signo
        const a = atom()
        if (isOp("**")) {
            take()
            const b = unary()
            if (Math.abs(b) > 1000) throw new Error("too big")
            return Math.pow(a, b)
        }
        return a
    }
    function atom() {
        const tk = take()
        if (!tk) throw new Error("end")
        if (tk.t === "num") return tk.v
        if (tk.t === "op" && tk.v === "(") { const v = expr(); if (!isOp(")")) throw new Error("paren"); take(); return v }
        if (tk.t === "id") {
            if (isOp("(")) {
                if (!(tk.v in FUNCS)) throw new Error("func")
                take()
                const args = []
                if (!isOp(")")) { args.push(expr()); while (isOp(",")) { take(); args.push(expr()) } }
                if (!isOp(")")) throw new Error("paren")
                take()
                return FUNCS[tk.v].apply(null, args)
            }
            if (tk.v in NAMES) return NAMES[tk.v]
        }
        throw new Error("unsupported")
    }
    const v = expr()
    if (p !== tokens.length) throw new Error("trailing")
    return v
}

function fmt(r) {
    if (Number.isInteger(r) && Math.abs(r) < 1e15) return String(r)
    // como "%.10g" de Python
    const exp = r === 0 ? 0 : Math.floor(Math.log10(Math.abs(r)))
    if (exp < -4 || exp >= 10) {
        let [m, e] = r.toExponential(9).split("e")
        m = m.replace(/\.?0+$/, "")
        const n = parseInt(e, 10)
        return `${m}e${n < 0 ? "-" : "+"}${String(Math.abs(n)).padStart(2, "0")}`
    }
    return r.toPrecision(10).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "")
}

function calc(q) {
    let s = q.trim().replace(/\^/g, "**").replace(/×/g, "*").replace(/÷/g, "/")
    s = s.replace(/(\d),(?=\d)/g, "$1.")
    s = s.replace(/([\d)\s])x(?=[\d(\s])/g, "$1*")
    if (!/\d/.test(s) || !/[-+*/%()]|[a-z]\(/.test(s) || s.length > 200) return null
    let r
    try { r = parse(tokenize(s)) } catch (e) { return null }
    if (typeof r !== "number" || !isFinite(r)) return null
    return fmt(r)
}
