/**
 * PDB Edge — backend alternativo sobre Durable Objects
 *
 * POR QUE EXISTE
 * --------------
 * El backend actual (pdb-edge) guarda la PDB en D1 y paga por FILA leida. Con
 * un modelo jerarquico como ^GLOBAL, cada $ORDER barre N filas y cada agente
 * que despierta y reconstruye su estado hace varias. Este backend existe para
 * MEDIR si un Durable Object sale mas barato en el patron real, no para
 * sustituir nada a ciegas.
 *
 * LA IDEA
 * -------
 * Un DO tiene RAM propia y almacenamiento persistente. El truco es NO tocar
 * `storage` en cada operacion:
 *
 *   - Al despertar (o al primer acceso a un namespace) se carga el NS entero
 *     en un Map. Eso es UNA lectura (bulk), no N.
 *   - GET/ORDER/DATA/KILL trabajan sobre el Map: microsegundos, cero coste.
 *   - Las escrituras se acumulan y se vuelcan al final del turno, una sola
 *     vez por clave tocada (write coalescing).
 *
 * Asi una sesion de trabajo cuesta 1 lectura bulk + K escrituras, en vez de
 * N lecturas + K escrituras.
 *
 * IMPORTANTE: esto NO usa KV ni R2. El `storage` del propio DO es durable:
 * sobrevive a reinicios e hibernacion. Un snapshot externo solo haria falta
 * para replicar a otro nodo, que es otro problema (DDP).
 *
 * CONTRATO: identico al de operations.ts (D1). Cambiar de backend no debe
 * cambiar la semantica, solo donde se guardan los bytes.
 */

// ── Tipos minimos del runtime de Durable Objects ────────────────────────────
// Se declaran aqui para no depender de @cloudflare/workers-types en el repo.

export interface DoStorage {
  get<T = unknown>(key: string): Promise<T | undefined>
  put<T = unknown>(key: string, value: T): Promise<void>
  delete(key: string): Promise<boolean>
  list<T = unknown>(opts?: { prefix?: string; limit?: number }): Promise<Map<string, T>>
  deleteAll(): Promise<void>
}

export interface DoState {
  storage: DoStorage
  blockConcurrencyWhile<T>(fn: () => Promise<T>): Promise<T>
}

// ── Formato del arbol en RAM ────────────────────────────────────────────────
//
// Un nodo es un Map de subindice -> hijo. El valor de una clave vive bajo la
// clave reservada VAL, que no puede colisionar porque los subindices de M son
// strings y VAL se guarda aparte del mapa de hijos.
//
//   { VAL: <valor>, KIDS: Map<string, Nodo> }
//
// Se separa VAL de KIDS para que $ORDER no tenga que filtrar: recorre KIDS.

const VAL = '\u0000val'
const KIDS = '\u0000kids'

interface Nodo {
  v?: string
  k: Map<string, Nodo>
}

function nuevoNodo(): Nodo {
  return { k: new Map() }
}

// ── Backend ─────────────────────────────────────────────────────────────────

export class PdbDo {
  private state: DoState
  /** Namespaces cargados en RAM. Carga perezosa: solo al primer acceso. */
  private ns = new Map<string, Nodo>()
  /** Claves modificadas pendientes de volcar, por namespace. */
  private sucio = new Map<string, Set<string>>()
  /** Contadores para el informe de coste. Ver stats(). */
  private lecturaBulk = 0
  private escrituras = 0

  constructor(state: DoState) {
    this.state = state
  }

  // ── Carga perezosa ────────────────────────────────────────────────────────

  /**
   * Trae un namespace a RAM si no esta ya. UNA lectura por namespace y
   * sesion, no una por operacion: ahi esta el ahorro frente a D1.
   *
   * Se guarda como un unico valor (el arbol serializado). Alternativa
   * descartada: una clave de storage por subindice, que seria una lectura por
   * $GET y no ahorraria nada frente a D1.
   */
  private async cargar(ns: string): Promise<Nodo> {
    const ya = this.ns.get(ns)
    if (ya) return ya

    const plano = await this.state.storage.get<Record<string, string>>(`ns:${ns}`)
    this.lecturaBulk++

    const raiz = nuevoNodo()
    if (plano) {
      for (const [subkey, valor] of Object.entries(plano)) {
        this.insertarPorSubkey(raiz, subkey, valor)
      }
    }
    this.ns.set(ns, raiz)
    return raiz
  }

  /**
   * Reconstruye el arbol a partir de las claves planas. La clave llega en el
   * formato MUMPS ya codificado (\x02 + sub + \xff...), asi que se reusa el
   * mismo formato que D1: cero divergencia de encoding entre backends.
   */
  private insertarPorSubkey(raiz: Nodo, subkey: string, valor: string): void {
    const subs = decodificarSubs(subkey)
    let n = raiz
    for (const s of subs) {
      let hijo = n.k.get(s)
      if (!hijo) {
        hijo = nuevoNodo()
        n.k.set(s, hijo)
      }
      n = hijo
    }
    n.v = valor
  }

  // ── Volcado ───────────────────────────────────────────────────────────────

  private marcarSucio(ns: string, subs: (string | number)[]): void {
    const clave = codificarSubs(subs)
    let set = this.sucio.get(ns)
    if (!set) {
      set = new Set()
      this.sucio.set(ns, set)
    }
    set.add(clave)
  }

  /**
   * Vuelca a `storage` los namespaces tocados. Una escritura por namespace y
   * lote, no una por SET: el motor ya agrupa las escrituras de un turno en
   * una transaccion (begin_slice_tx/end_slice_tx), asi que el consumidor
   * llama a flush() al cerrar el turno.
   *
   * El objeto se reescribe entero. Es aceptable porque la PDB de un shard es
   * pequeña; si algun dia deja de serlo, habria que pasar a claves por
   * subarbol. Se deja anotado en vez de optimizarlo sin medir.
   */
  async flush(): Promise<{ escrituras: number }> {
    let n = 0
    for (const [ns, claves] of this.sucio) {
      if (claves.size === 0) continue
      const raiz = this.ns.get(ns)
      if (!raiz) continue
      const plano: Record<string, string> = {}
      aplanar(raiz, [], plano)
      await this.state.storage.put(`ns:${ns}`, plano)
      n++
      this.escrituras++
      claves.clear()
    }
    return { escrituras: n }
  }

  /** Contadores del trabajo hecho desde el ultimo reset. Para el benchmark. */
  stats() {
    return { lecturaBulk: this.lecturaBulk, escrituras: this.escrituras }
  }

  resetStats(): void {
    this.lecturaBulk = 0
    this.escrituras = 0
  }

  // ── Operaciones M ─────────────────────────────────────────────────────────
  // Mismo contrato que operations.ts. Nada de SQL: se navega el arbol.

  async set(ns: string, subs: (string | number)[], value: any): Promise<void> {
    const raiz = await this.cargar(ns)
    let n = raiz
    for (const s of subs) {
      const key = String(s)
      let hijo = n.k.get(key)
      if (!hijo) {
        hijo = nuevoNodo()
        n.k.set(key, hijo)
      }
      n = hijo
    }
    n.v = typeof value === 'string' ? value : JSON.stringify(value)
    this.marcarSucio(ns, subs)
  }

  async get(ns: string, subs: (string | number)[]): Promise<any | null> {
    const raiz = await this.cargar(ns)
    let n: Nodo | undefined = raiz
    for (const s of subs) {
      n = n.k.get(String(s))
      if (!n) return null
    }
    if (n.v === undefined) return null
    try { return JSON.parse(n.v) } catch { return n.v }
  }

  /**
   * $ORDER(^ns(subs), dir) — siguiente hermano en el ultimo nivel.
   * Recorrer un Map ordenado en RAM, no una consulta: aqui esta la diferencia
   * de coste frente a D1.
   */
  async order(ns: string, subs: (string | number)[], dir: 1 | -1 = 1): Promise<string | null> {
    const raiz = await this.cargar(ns)
    // subs vacio o [""] => primer nivel
    const camino = subs.length === 1 && subs[0] === '' ? [] : subs
    const ultimo = camino.length ? String(camino[camino.length - 1]) : null

    let padre: Nodo | undefined = raiz
    for (let i = 0; i < camino.length - 1; i++) {
      padre = padre.k.get(String(camino[i]))
      if (!padre) return null
    }
    if (!padre) return null

    const claves = [...padre.k.keys()].sort(dir === 1 ? cmpAsc : cmpDesc)
    if (ultimo === null) return claves.length ? claves[0] : null

    const i = claves.indexOf(ultimo)
    if (i === -1) {
      // El subindice de partida no existe: devolver el primero que lo supere.
      const sig = claves.find(c => (dir === 1 ? cmpAsc(c, ultimo) > 0 : cmpAsc(c, ultimo) < 0))
      return sig ?? null
    }
    return claves[i + dir] ?? null
  }

  /** $DATA: 0 = no existe, 1 = valor, 10 = hijos, 11 = ambos. */
  async data(ns: string, subs: (string | number)[]): Promise<number> {
    const raiz = await this.cargar(ns)
    let n: Nodo | undefined = raiz
    for (const s of subs) {
      n = n.k.get(String(s))
      if (!n) return 0
    }
    const v = n.v !== undefined ? 1 : 0
    const k = n.k.size > 0 ? 10 : 0
    return v + k
  }

  async kill(ns: string, subs: (string | number)[]): Promise<number> {
    const raiz = await this.cargar(ns)
    let padre: Nodo | undefined = raiz
    for (let i = 0; i < subs.length - 1; i++) {
      padre = padre.k.get(String(subs[i]))
      if (!padre) return 0
    }
    if (!padre) return 0
    const key = String(subs[subs.length - 1])
    const habia = padre.k.has(key)
    padre.k.delete(key)
    if (habia) this.marcarSucio(ns, subs)
    return habia ? 1 : 0
  }

  async incr(ns: string, subs: (string | number)[], delta = 1): Promise<number> {
    const actual = await this.get(ns, subs)
    const num = typeof actual === 'number' ? actual : parseFloat(String(actual ?? 0)) || 0
    const nuevo = num + delta
    await this.set(ns, subs, nuevo)
    return nuevo
  }

  /** $ORDER de todos los namespaces (equivalente a nsKeys de D1). */
  async nsKeys(): Promise<string[]> {
    // Los namespaces cargados en RAM ya se conocen; los de storage se listan
    // solo si hace falta. Para el uso normal basta con los cargados.
    const set = new Set(this.ns.keys())
    const lista = await this.state.storage.list({ prefix: 'ns:' })
    for (const k of lista.keys()) set.add(k.slice(3))
    return [...set].sort()
  }
}

// ── Utilidades del arbol ────────────────────────────────────────────────────

function aplanar(n: Nodo, camino: string[], out: Record<string, string>): void {
  if (n.v !== undefined) out[codificarSubs(camino)] = n.v
  for (const [k, hijo] of n.k) {
    camino.push(k)
    aplanar(hijo, camino, out)
    camino.pop()
  }
}

/** Comparacion de subindices: numerica si ambos lo son, si no lexicografica. */
function cmpAsc(a: string, b: string): number {
  const na = Number(a), nb = Number(b)
  const aNum = a !== '' && !Number.isNaN(na)
  const bNum = b !== '' && !Number.isNaN(nb)
  if (aNum && bNum) return na - nb
  return a < b ? -1 : a > b ? 1 : 0
}

function cmpDesc(a: string, b: string): number {
  return -cmpAsc(a, b)
}

// ── Encoding MUMPS: MISMO formato que encode.ts de pdb-edge ─────────────────
// Se replica aqui para que este fichero sea autocontenido y el benchmark no
// dependa de dos copias del encoder. Si cambia el formato, cambia en los dos
// sitios: es el unico punto donde D1 y DO comparten representacion.

const SEP_STR = '\x02'
const SEP_END = '\xff'

export function codificarSubs(subs: (string | number)[]): string {
  return subs.map(s => `${SEP_STR}${String(s)}${SEP_END}`).join('')
}

export function decodificarSubs(subkey: string): string[] {
  const out: string[] = []
  let i = 0
  while (i < subkey.length) {
    if (subkey[i] !== SEP_STR) { i++; continue }
    const ini = i + 1
    const fin = subkey.indexOf(SEP_END, ini)
    if (fin === -1) break
    out.push(subkey.slice(ini, fin))
    i = fin + 1
  }
  return out
}
