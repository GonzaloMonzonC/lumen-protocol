// Smoke test completo del paquete WASM
import init, { m_compile, m_execute, m_execute_raw, m_version } from './pkg/lumen_mlight.js';
import { readFile } from 'node:fs/promises';

const bytes = await readFile('./pkg/lumen_mlight_bg.wasm');
await init({ module_or_path: bytes });

console.log('version:', m_version());
let pass = 0, fail = 0;

const tests = [
  ['simple', 'S x=42 W x', null],
  ['global set+get', 'S ^G("a")=21 S y=^G("a")*2 W y', null],
  ['$HOROLOG no panica', 'S h=$H W $P(h,",")>60000', null],
  ['$ZH no panica', 'S z=$ZH H 0 W z>=0', null],
  ['for loop', 'S t=0 F i=1:1:10 S t=t+i W t', null],
  ['string fn', 'S s="lumen" W $L(s)', null],
];

for (const [name, code] of tests) {
  try {
    const out = m_execute(m_compile(code), '[]');
    console.log(`OK   ${name} → ${JSON.stringify(out)}`);
    pass++;
  } catch (e) {
    console.log(`FAIL ${name}: ${String(e).slice(0, 100)}`);
    fail++;
  }
}

// globals precargados (memoria compartida simulada entre ejecuciones)
try {
  const c = m_compile('S n=^MEMORIA("visitas")+1 S ^MEMORIA("visitas")=n W "visita ",n');
  const r1 = m_execute(c, '[{"ns":"MEMORIA","subs":["visitas"],"value":0}]');
  const r2 = m_execute(c, '[{"ns":"MEMORIA","subs":["visitas"],"value":1}]');
  console.log(`OK   memoria compartida → ${JSON.stringify(r1)}, ${JSON.stringify(r2)} (estado persiste vía globals JSON)`);
  pass++;
} catch (e) {
  console.log(`FAIL memoria compartida: ${String(e).slice(0, 100)}`);
  fail++;
}

console.log(`\nRESULTADO: ${pass} pass / ${fail} fail`);
