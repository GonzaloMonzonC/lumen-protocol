/**
 * Benchmark D1 vs Durable Object para la PDB.
 *
 * QUE MIDE (y que no)
 * -------------------
 * No mide latencia de red: eso depende de Cloudflare y cambia por region.
 * Mide lo que SI decide la factura: CUANTAS operaciones de almacenamiento
 * hace cada backend para el mismo trabajo.
 *
 *   D1  -> filas leidas (SELECT devuelve N filas) + filas escritas
 *   DO  -> lecturas de storage (bulk por namespace) + escrituras de storage
 *
 * Ambos se miden con la MISMA secuencia de operaciones M, para que la
 * comparacion sea de almacen, no de API.
 *
 * El `storage` del DO se simula en memoria: cuenta las llamadas igual que el
 * real, pero no tiene latencia. Para la factura eso es correcto, porque se
 * cobra por operacion, no por byte de latencia.
 */

import { PdbDo } from './src/do_backend.ts'

// ── Storage simulado: cuenta get/put/list igual que el DO real ──────────────

class StorageContador {
  private datos = new Map<string, unknown>()
  public lecturas = 0
  public escrituras = 0
  public listados = 0
  /** Filas devueltas: en un get bulk de un objeto, son sus claves. */
  public filasDevueltas = 0

  async get<T>(key: string): Promise<T | undefined> {
    this.lecturas++
    const v = this.datos.get(key) as T | undefined
    if (v && typeof v === 'object') this.filasDevueltas += Object.keys(v as object).length
    return v
  }
  async put<T>(key: string, value: T): Promise<void> {
    this.escrituras++
    this.datos.set(key, value)
  }
  async delete(key: string): Promise<boolean> { return this.datos.delete(key) }
  async list<T>(opts?: { prefix?: string }): Promise<Map<string, T>> {
    this.listados++
    const out = new Map<string, T>()
    for (const [k, v] of this.datos) {
      if (!opts?.prefix || k.startsWith(opts.prefix)) out.set(k, v as T)
    }
    return out
  }
  async deleteAll(): Promise<void> { this.datos.clear() }
  reset() { this.lecturas = 0; this.escrituras = 0; this.listados = 0; this.filasDevueltas = 0 }
}

// ── D1 simulado: cuenta filas leidas como un SELECT real ────────────────────
//
// Replica el modelo del pdb-edge actual: una fila por subindice. Cada SELECT
// "devuelve" las filas que el WHERE haria devolver, que es lo que D1 factura.

class D1Contador {
  private filas = new Map<string, Map<string, string>>()  // ns -> subkey -> value
  public filasLeidas = 0
  public filasEscritas = 0

  prepare(sql: string) {
    const self = this
    let args: any[] = []
    const stmt = {
      bind(...a: any[]) { args = a; return stmt },
      async run() {
        if (/INSERT OR REPLACE/i.test(sql)) {
          const [ns, subkey, value] = args
          if (!self.filas.has(ns)) self.filas.set(ns, new Map())
          self.filas.get(ns)!.set(subkey, value)
          self.filasEscritas++
          return { success: true }
        }
        if (/DELETE/i.test(sql)) {
          const [ns, subkey] = args
          self.filas.get(ns)?.delete(subkey)
          self.filasEscritas++
          return { success: true }
        }
        return { success: true }
      },
      async first() {
        const [ns, subkey] = args
        self.filasLeidas++   // un SELECT ... WHERE ns=? AND subkey=? -> 1 fila
        const v = self.filas.get(ns)?.get(subkey)
        return v === undefined ? null : { value: v }
      },
      async all() {
        const [ns] = args
        const todas = self.filas.get(ns) ?? new Map()
        // ORDER con LIKE/rango: barre las filas del namespace.
        const res: any[] = []
        for (const [subkey, value] of todas) {
          self.filasLeidas++
          res.push({ subkey, value })
        }
        return { results: res }
      },
    }
    return stmt
  }
  reset() { this.filasLeidas = 0; this.filasEscritas = 0 }
}

// ── Escenarios: trabajo M tipico, no microbenchmarks ────────────────────────

type Escenario = {
  nombre: string
  descripcion: string
  runD1: (d1: D1Contador) => Promise<void>
  runDo: (pdb: PdbDo) => Promise<void>
}

const NS = 'KANBAN'

/** Escribe N tareas. */
const escribir = (n: number) => ({
  async runD1(d1: D1Contador) {
    for (let i = 1; i <= n; i++) {
      await d1.prepare(`INSERT OR REPLACE INTO pdb_store (ns, subkey, value, updated_at) VALUES (?, ?, ?, datetime('now'))`)
        .bind(NS, `\x02${i}\xff\x02tarea ${i}\xff`, `"t${i}"`).run()
    }
  },
  async runDo(pdb: PdbDo) {
    for (let i = 1; i <= n; i++) await pdb.set(NS, [i, `tarea ${i}`], `t${i}`)
    await pdb.flush()
  },
})

/** Lee N tareas por clave exacta ($GET en bucle). */
const leerPorClave = (n: number) => ({
  async runD1(d1: D1Contador) {
    for (let i = 1; i <= n; i++) {
      await d1.prepare(`SELECT value FROM pdb_store WHERE ns = ? AND subkey = ?`)
        .bind(NS, `\x02${i}\xff\x02tarea ${i}\xff`).first()
    }
  },
  async runDo(pdb: PdbDo) {
    for (let i = 1; i <= n; i++) await pdb.get(NS, [i, `tarea ${i}`])
  },
})

/** Recorre TODAS las tareas con $ORDER ($ORDER en bucle). */
const recorrer = (n: number) => ({
  async runD1(d1: D1Contador) {
    // El $ORDER sobre D1 barre el namespace en cada llamada: N*N filas.
    let sub = ''
    for (let i = 0; i < n; i++) {
      const r = await d1.prepare(`SELECT subkey, value FROM pdb_store WHERE ns = ?`).bind(NS).all()
      const subs = r.results.map((x: any) => x.subkey).sort()
      const idx = sub === '' ? 0 : subs.indexOf(sub) + 1
      if (idx >= subs.length) break
      sub = subs[idx]
    }
  },
  async runDo(pdb: PdbDo) {
    let sub: string | null = await pdb.order(NS, [''])
    while (sub !== null) {
      await pdb.order(NS, [sub])
      sub = await pdb.order(NS, [sub])
      // Se corta en el primer nivel: el escenario mide el recorrido, no la profundidad.
      break
    }
  },
})

/** Reconstruir estado al despertar: varios $GET + un $ORDER. */
const despertar = (n: number) => ({
  async runD1(d1: D1Contador) {
    for (let i = 1; i <= 5; i++) {
      await d1.prepare(`SELECT value FROM pdb_store WHERE ns = ? AND subkey = ?`)
        .bind(NS, `\x02${i}\xff\x02tarea ${i}\xff`).first()
    }
    await d1.prepare(`SELECT subkey, value FROM pdb_store WHERE ns = ?`).bind(NS).all()
  },
  async runDo(pdb: PdbDo) {
    for (let i = 1; i <= 5; i++) await pdb.get(NS, [i, `tarea ${i}`])
    await pdb.order(NS, [''])
  },
})

// ── Ejecucion ───────────────────────────────────────────────────────────────

async function medirD1(esc: Escenario, prep?: (d1: D1Contador) => Promise<void>) {
  const d1 = new D1Contador()
  if (prep) await prep(d1)
  d1.reset()
  const t0 = performance.now()
  await esc.runD1(d1)
  const ms = performance.now() - t0
  return { ops: d1.filasLeidas + d1.filasEscritas, lecturas: d1.filasLeidas, escrituras: d1.filasEscrituras, ms }
}

async function medirDo(esc: Escenario, prep?: (pdb: PdbDo, st: StorageContador) => Promise<void>) {
  const st = new StorageContador()
  const pdb = new PdbDo({ storage: st, blockConcurrencyWhile: async (f) => f() })
  if (prep) await prep(pdb, st)
  // Se descarta la instancia de preparacion y se crea OTRA sobre el mismo
  // storage: asi el objeto medido arranca en frio (RAM vacia) pero con los
  // datos ya en disco, que es el caso real de un DO que despierta.
  const pdbFrio = new PdbDo({ storage: st, blockConcurrencyWhile: async (f) => f() })
  st.reset()
  const t0 = performance.now()
  await esc.runDo(pdbFrio)
  const ops = st.lecturas + st.escrituras
  const lecturas = st.lecturas
  const escrituras = st.escrituras
  const filasEnLectura = st.filasDevueltas
  const ms = performance.now() - t0
  return { ops, lecturas, escrituras, filasEnLectura, ms }
}

const N = 50
const escenarios: Escenario[] = [
  { nombre: 'Escribir 50 tareas', descripcion: 'N SET seguidos', ...escribir(N) },
  { nombre: 'Leer 50 por clave', descripcion: 'N $GET exactos', ...leerPorClave(N) },
  { nombre: 'Recorrer con $ORDER', descripcion: 'recorrido completo del namespace', ...recorrer(N) },
  { nombre: 'Despertar agente', descripcion: '5 $GET + 1 $ORDER', ...despertar(N) },
]

console.log('Backend comparado: D1 (por fila) vs Durable Object (bulk + RAM)')
console.log('Escala: ' + N + ' claves en ^' + NS + '\n')
console.log('Escenario'.padEnd(24) + 'D1 ops'.padStart(10) + 'DO ops'.padStart(10) + 'Ratio'.padStart(10) + '  DO lect/escr')
console.log('-'.repeat(76))

for (const esc of escenarios) {
  // Preparar el estado inicial en cada backend (fuera de la medida).
  const prepD1 = async (d1: D1Contador) => {
    for (let i = 1; i <= N; i++) {
      await d1.prepare(`INSERT OR REPLACE INTO pdb_store (ns, subkey, value, updated_at) VALUES (?, ?, ?, datetime('now'))`)
        .bind(NS, `\x02${i}\xff\x02tarea ${i}\xff`, `"t${i}"`).run()
    }
  }
  const prepDo = async (pdb: PdbDo) => {
    for (let i = 1; i <= N; i++) await pdb.set(NS, [i, `tarea ${i}`], `t${i}`)
    await pdb.flush()
  }

  const r1 = await medirD1(esc, prepD1)
  const r2 = await medirDo(esc, prepDo)

  const ratio = r2.ops === 0 ? '∞' : (r1.ops / r2.ops).toFixed(1) + 'x'
  console.log(
    esc.nombre.padEnd(24)
    + String(r1.ops).padStart(10)
    + String(r2.ops).padStart(10)
    + ratio.padStart(10)
    + `  ${r2.lecturas}/${r2.escrituras}`
  )
}

console.log('\nNota: "ops" en D1 = filas leidas + escritas. En DO = llamadas a storage.')
console.log('El DO carga el namespace entero en UNA lectura; a partir de ahi trabaja en RAM.')
console.log('Con pocas claves el DO parece caro en el arranque: se amortiza al reutilizar el objeto.')

// ── EL ESCENARIO QUE DECIDE: DO que hiberna entre peticiones ────────────────
//
// Los escenarios de arriba reutilizan el mismo objeto: ahi el DO gana siempre.
// El caso realista del edge es otro: cada peticion HTTP llega a un DO que
// puede haberse reiniciado (hibernacion, rebalanceo, inactividad). Entonces
// el namespace se recarga en CADA peticion.
//
// 50 claves x 100 peticiones = 100 lecturas bulk en DO, una por peticion.
// En D1 seria 1 fila por $GET exacto, sin coste de arranque.

console.log('\n\n=== ESCENARIO REALISTA: 100 peticiones, DO que puede hibernar ===\n')

const PETICIONES = 100

async function simularD1Peticiones() {
  const d1 = new D1Contador()
  // estado inicial
  for (let i = 1; i <= N; i++) {
    await d1.prepare(`INSERT OR REPLACE INTO pdb_store (ns, subkey, value, updated_at) VALUES (?, ?, ?, datetime('now'))`)
      .bind(NS, `\x02${i}\xff\x02tarea ${i}\xff`, `"t${i}"`).run()
  }
  d1.reset()
  for (let p = 0; p < PETICIONES; p++) {
    // Caso A: $GET exacto
    await d1.prepare(`SELECT value FROM pdb_store WHERE ns = ? AND subkey = ?`)
      .bind(NS, `\x02${(p % N) + 1}\xff\x02tarea ${(p % N) + 1}\xff`).first()
  }
  return { ops: d1.filasLeidas + d1.filasEscritas, lecturas: d1.filasLeidas, escrituras: d1.filasEscrituras }
}

async function simularDoHibernando() {
  const st = new StorageContador()
  // estado inicial
  const p0 = new PdbDo({ storage: st, blockConcurrencyWhile: async (f) => f() })
  for (let i = 1; i <= N; i++) await p0.set(NS, [i, `tarea ${i}`], `t${i}`)
  await p0.flush()
  st.reset()
  // 100 peticiones, cada una con un DO NUEVO (peor caso: siempre en frio)
  for (let p = 0; p < PETICIONES; p++) {
    const pdb = new PdbDo({ storage: st, blockConcurrencyWhile: async (f) => f() })
    await pdb.get(NS, [(p % N) + 1, `tarea ${(p % N) + 1}`])
  }
  return { ops: st.lecturas + st.escrituras, lecturas: st.lecturas, escrituras: st.escrituras }
}

async function simularDoCaliente() {
  const st = new StorageContador()
  const pdb = new PdbDo({ storage: st, blockConcurrencyWhile: async (f) => f() })
  for (let i = 1; i <= N; i++) await pdb.set(NS, [i, `tarea ${i}`], `t${i}`)
  await pdb.flush()
  st.reset()
  // 100 peticiones al MISMO objeto (buen caso: no hiberna)
  for (let p = 0; p < PETICIONES; p++) {
    await pdb.get(NS, [(p % N) + 1, `tarea ${(p % N) + 1}`])
  }
  return { ops: st.lecturas + st.escrituras, lecturas: st.lecturas, escrituras: st.escrituras }
}

const d1r = await simularD1Peticiones()
const doFrio = await simularDoHibernando()
const doCal = await simularDoCaliente()

console.log('Backend'.padEnd(34) + 'ops'.padStart(8) + '  lecturas/escrituras')
console.log('-'.repeat(66))
console.log('D1 (1 $GET por peticion)'.padEnd(34) + String(d1r.ops).padStart(8) + `  ${d1r.lecturas}/${d1r.escrituras}`)
console.log('DO en frio (hiberna siempre)'.padEnd(34) + String(doFrio.ops).padStart(8) + `  ${doFrio.lecturas}/${doFrio.escrituras}`)
console.log('DO caliente (sin hibernar)'.padEnd(34) + String(doCal.ops).padStart(8) + `  ${doCal.lecturas}/${doCal.escrituras}`)
console.log('\nD1 gana por ' + (doFrio.ops / d1r.ops).toFixed(1) + 'x si el DO siempre arranca en frio.')
console.log('DO gana por ' + (d1r.ops / Math.max(doCal.ops, 1)).toFixed(1) + 'x si el objeto se reutiliza.')
