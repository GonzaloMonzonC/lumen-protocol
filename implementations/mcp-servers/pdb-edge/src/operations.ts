/**
 * PDB Edge — Core Operations (SET/GET/ORDER/DATA/KILL/MERGE/INCR)
 * 
 * Implements MUMPS-style ^GLOBAL operations over D1 (SQLite).
 * Ported from pdb_tools.py to TypeScript.
 */

import { encodeSubs, encodePrefix, decodeSubs, decodeLastSub, incrementBytes } from './encode'

export interface D1Database {
  prepare(sql: string): D1PreparedStatement
}

export interface D1PreparedStatement {
  bind(...args: any[]): D1PreparedStatement
  run(): Promise<{ success: boolean; meta?: any }>
  first<T = any>(): Promise<T | null>
  all<T = any>(): Promise<{ results: T[] }>
}

// ── SET ^ns(subs) = value ──

export async function set(
  db: D1Database,
  ns: string,
  subs: (string | number)[],
  value: any
): Promise<void> {
  const subkey = encodeSubs(subs)
  const strValue = typeof value === 'string' ? value : JSON.stringify(value)
  
  await db.prepare(
    `INSERT OR REPLACE INTO pdb_store (ns, subkey, value, updated_at)
     VALUES (?, ?, ?, datetime('now'))`
  ).bind(ns, subkey, strValue).run()
}

// ── GET $GET(^ns(subs)) ──

export async function get(
  db: D1Database,
  ns: string,
  subs: (string | number)[]
): Promise<any | null> {
  const subkey = encodeSubs(subs)
  const row = await db.prepare(
    `SELECT value FROM pdb_store WHERE ns = ? AND subkey = ?`
  ).bind(ns, subkey).first<{ value: string }>()
  
  if (!row) return null
  
  try { return JSON.parse(row.value) }
  catch { return row.value }
}

// ── ORDER $ORDER(^ns(subs), direction) ──
// Returns the NEXT subscript at the level of the last provided subscript.
// Pass subs=[""] to start iteration at root level.
// Pass subs=["foo"] to get next sibling after "foo".

export async function order(
  db: D1Database,
  ns: string,
  subs: (string | number)[],
  direction: 1 | -1 = 1
): Promise<string | number | null> {
  // Build prefix: the parent path
  const parentSubs = subs.slice(0, -1)
  const lastSub = subs.length > 0 ? subs[subs.length - 1] : ''
  
  const parentPrefix = encodeSubs(parentSubs)
  const searchKey = encodePrefix([...parentSubs, lastSub])
  
  // For $ORDER, we need to find subkeys that have our prefix + one more level
  // A subkey at level N that starts with parentPrefix and has exactly N+1 levels
  // We do this by finding the next subkey after searchKey that starts with parentPrefix
  
  const op = direction === 1 ? '>' : '<'
  const orderDir = direction === 1 ? 'ASC' : 'DESC'
  
  const row = await db.prepare(
    `SELECT subkey FROM pdb_store
     WHERE ns = ? AND subkey ${op} ?
     ORDER BY subkey ${orderDir} LIMIT 1`
  ).bind(ns, searchKey).first<{ subkey: Uint8Array }>()
  
  if (!row) return null
  
  const foundSubs = decodeSubs(row.subkey)
  if (foundSubs.length <= parentSubs.length) return null
  
  return foundSubs[parentSubs.length]
}

// ── DATA $DATA(^ns(subs)) ──
// Returns: 0=no existe, 1=tiene valor, 10=tiene hijos, 11=ambos

export async function data(
  db: D1Database,
  ns: string,
  subs: (string | number)[]
): Promise<number> {
  const subkey = encodeSubs(subs)
  const parentPrefix = encodeSubs(subs)
  const nextPrefix = incrementBytes(parentPrefix)
  
  const row = await db.prepare(
    `SELECT
      (SELECT COUNT(*) FROM pdb_store WHERE ns = ? AND subkey = ?) as has_value,
      (SELECT COUNT(*) FROM pdb_store
       WHERE ns = ? AND subkey > ? AND subkey < ?) as has_children`
  ).bind(
    ns, subkey,
    ns, parentPrefix, nextPrefix
  ).first<{ has_value: number; has_children: number }>()
  
  if (!row) return 0
  const hasValue = row.has_value > 0 ? 1 : 0
  const hasChildren = row.has_children > 0 ? 10 : 0
  return (hasValue + hasChildren) as 0 | 1 | 10 | 11
}

// ── KILL ^ns(subs) — delete subtree ──

export async function kill(
  db: D1Database,
  ns: string,
  subs: (string | number)[]
): Promise<number> {
  const prefix = encodeSubs(subs)
  const nextPrefix = incrementBytes(prefix)
  
  const result = await db.prepare(
    `DELETE FROM pdb_store
     WHERE ns = ? AND subkey >= ? AND subkey < ?`
  ).bind(ns, prefix, nextPrefix).run()
  
  // Return number of deleted rows (not directly available from D1)
  // D1 run() returns meta.changes in some versions
  return 0
}

// ── INCR $INCREMENT(^ns(subs)) ──

export async function incr(
  db: D1Database,
  ns: string,
  subs: (string | number)[],
  increment: number = 1
): Promise<number> {
  const subkey = encodeSubs(subs)
  
  // Atomic increment via SQL
  const result = await db.prepare(
    `INSERT INTO pdb_store (ns, subkey, value, created_at, updated_at)
     VALUES (?, ?, '0', datetime('now'), datetime('now'))
     ON CONFLICT (ns, subkey) DO UPDATE SET
       value = CAST(CAST(value AS INTEGER) + ? AS TEXT),
       updated_at = datetime('now')
     RETURNING CAST(value AS INTEGER) as new_value`
  ).bind(ns, subkey, increment).first<{ new_value: number }>()
  
  return result?.new_value ?? increment
}

// ── MERGE ^target = ^source ──

export async function merge(
  db: D1Database,
  targetNs: string,
  targetSubs: (string | number)[],
  sourceNs: string,
  sourceSubs: (string | number)[]
): Promise<number> {
  const sourcePrefix = encodeSubs(sourceSubs)
  const targetPrefix = encodeSubs(targetSubs)
  const nextPrefix = incrementBytes(sourcePrefix)
  
  // Read all source rows and write to target
  const rows = await db.prepare(
    `SELECT subkey, value FROM pdb_store
     WHERE ns = ? AND subkey >= ? AND subkey < ?`
  ).bind(sourceNs, sourcePrefix, nextPrefix).all<{ subkey: Uint8Array; value: string }>()
  
  if (!rows.results.length) return 0
  
  let count = 0
  for (const row of rows.results) {
    const sourceDecoded = decodeSubs(row.subkey)
    const relativeSubs = sourceDecoded.slice(sourceSubs.length)
    const newSubs = [...decodeSubs(targetPrefix), ...relativeSubs]
    const newSubkey = encodeSubs(newSubs)
    
    await db.prepare(
      `INSERT OR REPLACE INTO pdb_store (ns, subkey, value, updated_at)
       VALUES (?, ?, ?, datetime('now'))`
    ).bind(targetNs, newSubkey, row.value).run()
    count++
  }
  
  return count
}

// ── Check if namespace exists ──

export async function nsExists(
  db: D1Database,
  ns: string
): Promise<boolean> {
  const row = await db.prepare(
    `SELECT COUNT(*) as n FROM pdb_store WHERE ns = ? LIMIT 1`
  ).bind(ns).first<{ n: number }>()
  return (row?.n ?? 0) > 0
}

// ── List keys in namespace (for pdb_ns_order) ──

export async function nsKeys(
  db: D1Database,
  ns: string,
  prefix?: string,
  limit: number = 20
): Promise<{ key: string; value: any }[]> {
  let sql = `SELECT subkey, value FROM pdb_store WHERE ns = ?`
  const params: any[] = [ns]
  
  if (prefix) {
    const prefixBuf = new TextEncoder().encode(prefix)
    sql += ` AND subkey >= ?`
    params.push(prefixBuf)
  }
  
  sql += ` ORDER BY subkey LIMIT ?`
  params.push(limit)
  
  const rows = await db.prepare(sql).bind(...params).all<{ subkey: Uint8Array; value: string }>()
  
  return rows.results.map(row => {
    let val: any = row.value
    try { val = JSON.parse(row.value) } catch {}
    return {
      key: decodeSubs(row.subkey).join(','),
      value: val
    }
  })
}
