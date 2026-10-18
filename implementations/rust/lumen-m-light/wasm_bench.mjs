/**
 * wasm_bench.mjs — ejecuta un programa M en el WASM y mide el tiempo.
 *
 * Uso:  node wasm_bench.mjs "<programa>" [reps]
 * Salida: JSON {ok, ms, n_globals, error}
 *
 * ms = media por ejecucion (compilacion EXCLUIDA, para comparar con el nativo,
 * que tambien compila pero en un paso aparte; se mide solo la ejecucion).
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PKG_DIR = join(__dirname, 'pkg');

function parse(v) {
    if (typeof v === 'string') {
        try { return JSON.parse(v); } catch { return v; }
    }
    return v;
}

async function main() {
    const programa = process.argv[2] || '';
    const reps = parseInt(process.argv[3] || '5', 10);
    if (!programa) {
        console.error('uso: node wasm_bench.mjs "<programa>" [reps]');
        process.exit(2);
    }

    const mod = await import(pathToFileURL(join(PKG_DIR, 'lumen_mlight.js')).href);
    const wasmBytes = readFileSync(join(PKG_DIR, 'lumen_mlight_bg.wasm'));
    if (typeof mod.default === 'function') {
        await mod.default({ module_or_path: wasmBytes }).catch(async () => {
            await mod.default(wasmBytes);
        });
    }

    // compilar UNA vez (fuera de la medida)
    const crudo = mod.m_compile(programa);
    const bytes = crudo instanceof Uint8Array ? crudo : new Uint8Array(crudo);

    const gl = JSON.stringify([]);
    let ultimo = null;
    const t0 = process.hrtime.bigint();
    for (let k = 0; k < reps; k++) {
        ultimo = parse(mod.m_execute_raw(bytes, gl));
    }
    const msTotal = Number(process.hrtime.bigint() - t0) / 1e6;

    const globals = (ultimo && ultimo.globals) || [];
    if (!ultimo || typeof ultimo !== 'object' || Object.keys(ultimo).length === 0) {
        console.log(JSON.stringify({ ok: false, error: 'm_execute_raw devolvio vacio' }));
        process.exit(1);
    }

    console.log(JSON.stringify({
        ok: true,
        ms: msTotal / reps,
        n_globals: globals.length,
        exec: ultimo.execution,
    }));
}

main().catch((e) => {
    console.log(JSON.stringify({ ok: false, error: String(e).slice(0, 300) }));
    process.exit(1);
});
