/**
 * wasm_digest.mjs — ejecuta un programa M en el WASM y devuelve el digest canónico.
 *
 * Uso:  node wasm_digest.mjs "<programa M>"
 * Salida: JSON {ok, digest, n_globals, error}
 *
 * El digest usa el MISMO algoritmo que digest_canonico.py (v1). Si divergen, el
 * test cruzado miente: cambiar los dos a la vez.
 */
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_DIR = join(__dirname, 'pkg');

const VERSION = '1';
const SIG = 12;

function num(v) {
    if (typeof v !== 'number') return String(v);
    if (Number.isNaN(v)) return 'nan';
    if (v === Infinity) return 'inf';
    if (v === -Infinity) return '-inf';
    if (v === 0) return '0';
    if (Number.isInteger(v) && Math.abs(v) < 1e15) return String(v);
    let s = v.toPrecision(SIG);
    if (s.includes('.')) s = s.replace(/(\.\d*?)0+$/, '$1').replace(/\.$/, '');
    return s;
}

function valor(v) {
    if (v === null || v === undefined) return '\u0000none';
    if (typeof v === 'boolean') return v ? 'true' : 'false';
    if (typeof v === 'number') return num(v);
    if (typeof v === 'string') return v;
    return JSON.stringify(v);
}

function subs(s) {
    if (!s) return '';
    return s.map((x) => (typeof x === 'number' ? num(x) : String(x))).join('|');
}

function proyeccion(globals) {
    const lineas = (globals || []).map((g) => `${g.ns}\x1f${subs(g.subs)}\x1f${valor(g.value)}`);
    lineas.sort();
    return lineas;
}

function digestGlobals(globals) {
    const h = createHash('sha256');
    h.update(`v${VERSION}\x1e`);
    for (const l of proyeccion(globals)) {
        h.update(l, 'utf8');
        h.update(Buffer.from([0x1e]));
    }
    return h.digest('hex');
}

/** M_execute trabaja sobre código COMPILADO: hay que llamar a m_compile primero. */
function parse(v) {
    if (typeof v === 'string') {
        try { return JSON.parse(v); } catch { return v; }
    }
    return v;
}

async function main() {
    const programa = process.argv[2] || '';
    if (!programa) {
        console.error('uso: node wasm_digest.mjs "<programa>"');
        process.exit(2);
    }

    const mod = await import(pathToFileURL(join(PKG_DIR, 'lumen_mlight.js')).href);

    // init: el default export es la funcion de inicializacion de wasm-bindgen
    const wasmBytes = readFileSync(join(PKG_DIR, 'lumen_mlight_bg.wasm'));
    if (typeof mod.default === 'function') {
        await mod.default({ module_or_path: wasmBytes }).catch(async () => {
            await mod.default(wasmBytes);
        });
    }

    // 1. compilar. m_compile devuelve un Uint8Array con el JSON serializado
    //    byte a byte (no un objeto). m_execute espera el BYTECODE, no el JSON.
    const crudo = mod.m_compile(programa);
    const bytes = crudo instanceof Uint8Array ? crudo : new Uint8Array(crudo);
    const compilado = parse(Buffer.from(bytes).toString('utf8'));

    if (process.env.WASM_DEBUG) {
        console.error('DEBUG claves de m_compile:', Object.keys(compilado || {}));
    }

    // El bytecode puede venir como campo del JSON o ser el propio buffer.
    let bytecode = null;
    const cand = compilado && (compilado.bytecode || compilado.program || compilado.code);
    if (cand instanceof Uint8Array) bytecode = cand;
    else if (Array.isArray(cand)) bytecode = new Uint8Array(cand);
    else if (typeof cand === 'string') bytecode = new Uint8Array(Buffer.from(cand, 'base64'));
    else bytecode = bytes;      // el propio buffer compilado

    // Ejecutar. Se prueba primero m_execute_raw y, si devuelve vacio, m_execute.
    // Ambas esperan el BYTECODE como Uint8Array y los globals de ENTRADA como
    // JSON. La primera devuelve el resultado completo; la segunda, solo output.
    const gl = JSON.stringify([]);
    let r = parse(mod.m_execute_raw(bytes, gl));
    if (!r || typeof r !== 'object' || Object.keys(r).length === 0) {
        const r2 = parse(mod.m_execute(bytes, gl));
        if (r2 && typeof r2 === 'object' && Object.keys(r2).length) r = r2;
    }

    const globals = (r && r.globals) || [];

    // Diagnóstico: si no vuelven globals, decir que claves SÍ trae el resultado.
    // Es la diferencia clave con el motor nativo, que sí las devuelve.
    if (globals.length === 0 && process.env.WASM_DEBUG) {
        console.error('DEBUG claves del resultado:', Object.keys(r));
        console.error('DEBUG compiled keys:', Object.keys(compilado || {}));
        console.error('DEBUG muestra:', JSON.stringify(r).slice(0, 400));
    }

    const digest = digestGlobals(globals);

    console.log(JSON.stringify({
        ok: r.ok !== false,
        exec: r.execution,
        digest,
        n_globals: globals.length,
        error: r.error ? String(r.error).slice(0, 200) : null,
    }));
}

main().catch((e) => {
    console.log(JSON.stringify({ ok: false, error: String(e).slice(0, 300) }));
    process.exit(1);
});
