// ─────────────────────────────────────────────────────────────────────────────
// DDP-LUMEN Client (TypeScript) — CÓDIGO CANÓNICO DEL PROTOCOLO
// Fuente única: lumen-protocol/implementations/typescript/src/ddp-client.ts
//
// Este módulo es LA implementación TS del protocolo DDP-LUMEN v0.2 para
// Cloudflare Workers. Los workers del ecosistema (Zalo, Angi, Lisa, Tom, Gon,
// Campo) VENDEN este fichero (copia sincronizada) — NUNCA implementan su propio
// cliente (regla SSOT de código, Gonzalo 14-08-2026).
//
// Sync: copiar este fichero a cada worker con:
//   cp lumen-protocol/implementations/typescript/src/ddp-client.ts <worker>/src/ddp-client.ts
// Verificar con git diff que no hay divergencia.
//
// Protocolo:
//   - Escritura canónica: POST https://vm-api.cadences.app/ddp/push
//     body {ns, entries:[{subs:[...], value}]} — vm_api construye SET ^NS(...)=value
//   - Lectura canónica:  GET  https://vm-api.cadences.app/ddp/raw?ns=X&prefix=...&limit=N
//   - Auth M2M: HMAC-SHA256 ts+body+key (X-DDP-Timestamp, X-DDP-HMAC), clave
//     compartida DDP_HMAC_KEY (env del worker).
// ─────────────────────────────────────────────────────────────────────────────

export interface PdbEntry {
  subs: string[]
  value: string
}

export interface PdbPushResult {
  ok: boolean
  error?: string
}

function hmacHex(keyStr: string, data: string): Promise<string> {
  const enc = new TextEncoder()
  return crypto.subtle.importKey('raw', enc.encode(keyStr), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
    .then((key) => crypto.subtle.sign('HMAC', key, enc.encode(data)))
    .then((sig) => Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, '0')).join(''))
}

export function encodeSubkey(subs: string[]): string {
  // Codificación MUMPS: cada sub prefijado con \x02, separados por \xff, terminado en \xff
  const parts = subs.map((s) => '\x02' + s)
  return parts.join('\xff') + '\xff'
}

export const VM_API = 'https://vm-api.cadences.app'

/**
 * JSON-encode un valor con escapes ASCII (\uXXXX para no-ASCII).
 * CONVENCIÓN DEL PROTOCOLO: los valores viajan SIEMPRE como JSON ASCII-safe —
 * el motor M-Light/Rust corrompe literales con unicode real (→ se guarda como
 * cp1252 mojibake). Los escapes \u round-trippan perfecto (igual que el resto
 * del store, que ya usa ensure_ascii).
 */
export function jsonEsc(v: any): string {
  const s = JSON.stringify(v)
  return s.replace(/[^\x00-\x7F]/g, (c) => {
    const hex = c.charCodeAt(0).toString(16).padStart(4, '0')
    return '\\u' + hex
  })
}

/** POST /ddp/push con HMAC (ts+body+key). Formato nativo de vm_api: subs en claro. */
export async function pdbPush(env: any, ns: string, entries: PdbEntry[]): Promise<PdbPushResult> {
  try {
    const keyStr = (env as any).DDP_HMAC_KEY || ''
    if (!keyStr) return { ok: false, error: 'DDP_HMAC_KEY no configurada' }
    const body = JSON.stringify({ ns, entries })
    const ts = String(Math.floor(Date.now() / 1000))
    const sig = await hmacHex(keyStr, ts + body + keyStr)
    const res = await fetch(VM_API + '/ddp/push', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-DDP-Timestamp': ts,
        'X-DDP-HMAC': sig,
        'User-Agent': 'Mozilla/5.0 LUMEN-DDP/1.0',
      },
      body,
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) {
      const txt = await res.text().catch(() => '')
      return { ok: false, error: `HTTP ${res.status}: ${txt.slice(0, 120)}` }
    }
    const data = await res.json() as any
    return { ok: data?.ok !== false && data?.success !== false }
  } catch (e: any) {
    return { ok: false, error: e.message || String(e) }
  }
}

/** GET /ddp/raw?ns=X&prefix=a,b&limit=N&offset=M con HMAC (ts+path+key) — lectura canónica */
export async function pdbRead(env: any, ns: string, prefix?: string[], limit = 200, offset = 0): Promise<any[]> {
  try {
    const keyStr = (env as any).DDP_HMAC_KEY || ''
    if (!keyStr) return []
    const qs = new URLSearchParams({ ns, limit: String(limit) })
    if (prefix && prefix.length) qs.set('prefix', prefix.join(','))
    if (offset > 0) qs.set('offset', String(offset))
    const path = '/ddp/raw?' + qs.toString()
    const ts = String(Math.floor(Date.now() / 1000))
    const sig = await hmacHex(keyStr, ts + path + keyStr)
    const res = await fetch(VM_API + path, {
      headers: {
        'X-DDP-Timestamp': ts,
        'X-DDP-HMAC': sig,
        'User-Agent': 'Mozilla/5.0 LUMEN-DDP/1.0',
      },
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) return []
    const data = await res.json() as any
    return data?.entries || []
  } catch {
    return []
  }
}

// ── KANBAN (plano canónico de tareas del equipo) ──
// El contador KANBAN(counter,next_task) evita colisiones de task_N entre agentes.

/** Obtener el siguiente id de tarea KANBAN (contador propio: KANBAN(counter,next_task)) */
export async function kanbanNextTaskId(env: any): Promise<number> {
  try {
    const keyStr = (env as any).DDP_HMAC_KEY || ''
    if (!keyStr) return 0
    const path = '/ddp/raw?ns=KANBAN&prefix=counter&limit=1'
    const ts = String(Math.floor(Date.now() / 1000))
    const sig = await hmacHex(keyStr, ts + path + keyStr)
    const res = await fetch(VM_API + path, {
      headers: { 'X-DDP-Timestamp': ts, 'X-DDP-HMAC': sig, 'User-Agent': 'Mozilla/5.0 LUMEN-DDP/1.0' },
      signal: AbortSignal.timeout(15000),
    })
    if (!res.ok) return 0
    const data = await res.json() as any
    for (const e of data?.entries || []) {
      if (Array.isArray(e.subs) && e.subs[0] === 'counter' && e.subs[1] === 'next_task') {
        const raw = typeof e.value === 'string' ? e.value.replace(/^"|"$/g, '') : String(e.value)
        const n = parseInt(raw, 10)
        if (!isNaN(n)) return n
      }
    }
    return 0
  } catch {
    return 0
  }
}

// ── Helpers de tareas → KANBAN único (usadas por Angi PM; otros agentes pueden usarlas) ──
export const KANBAN_STATUS_MAP: Record<string, string> = {
  pendiente: 'backlog', en_curso: 'in_progress', completada: 'done',
  COMPLETADA: 'done', done: 'done', backlog: 'backlog', in_progress: 'in_progress',
}

/** Escribir una tarea nueva en el KANBAN único del PDB local. */
export async function pdbPushToKanban(env: any, tarea: any): Promise<void> {
  const next = await kanbanNextTaskId(env)
  if (!next) return // túnel no disponible — el emisor mantiene su espejo local
  const tid = `task_${next}`
  const st = KANBAN_STATUS_MAP[tarea.estado] || 'backlog'
  await pdbPush(env, 'KANBAN', [
    { subs: ['task', tid, 'title'], value: jsonEsc(tarea.titulo) },
    { subs: ['task', tid, 'status'], value: jsonEsc(st) },
    { subs: ['task', tid, 'priority'], value: jsonEsc(tarea.priority || 'medium') },
    { subs: ['task', tid, 'niche'], value: jsonEsc(tarea.niche || 'niche_91') },
    { subs: ['task', tid, 'owner'], value: jsonEsc(tarea.owner || tarea.agente || 'hermes') },
    { subs: ['task', tid, 'desc'], value: jsonEsc((tarea.detalle || tarea.desc || '').slice(0, 500)) },
    { subs: ['task', tid, 'src'], value: jsonEsc(tarea.src || 'ddp-client') },
    { subs: ['task', tid, 'src_id'], value: jsonEsc(tarea.id || '') },
    { subs: ['counter', 'next_task'], value: jsonEsc(next + 1) },
  ])
}

/** Reflejar un cambio de estado de tarea en el KANBAN (busca por src_id, paginado). */
export async function pdbUpdateKanbanStatus(env: any, srcId: string, estado: string): Promise<void> {
  const st = KANBAN_STATUS_MAP[estado] || 'backlog'
  // El KANBAN tiene miles de entries: paginar con offset hasta encontrar el src_id
  for (let offset = 0; offset < 12000; offset += 500) {
    const entries = await pdbRead(env, 'KANBAN', ['task'], 500, offset)
    if (!entries.length) break
    let found = false
    for (const e of entries) {
      const s = e.subs || []
      if (s.length >= 3 && s[0] === 'task' && s[1].startsWith('task_') && s[2] === 'src_id') {
        let v = e.value
        if (typeof v === 'string') v = v.replace(/^"|"$/g, '')
        if (v === srcId) {
          await pdbPush(env, 'KANBAN', [{ subs: ['task', s[1], 'status'], value: jsonEsc(st) }])
          return
        }
      }
    }
    if (!found && entries.length < 500) break
  }
}
