/**
 * PDB Edge — Hono API Server
 * 
 * REST API for PDB operations with auth by API key per namespace.
 * Lisa is the privileged writer; all agents can read.
 */

import { Hono } from 'hono'
import { cors } from 'hono/cors'
import * as ops from './operations'
import { subkeyToString } from './encode'

// ── Types ──

export interface Bindings {
  DB: ops.D1Database
  PDB_API_KEYS?: string  // JSON object: { "ns1": "key1", "ns2": "key2", ... }
  PDB_MASTER_KEY?: string  // Master key that can write to any ns
  WRITER_AGENTS?: string   // Comma-separated list of agent IDs allowed to write (default: "lisa")
}

interface ApiKeyMap {
  [ns: string]: string
}

// Namespaces que cada agente puede escribir
const AGENT_NS_MAP: Record<string, string[]> = {
  lisa: ['^Lisa', '^System'],
  angi: ['^Angi'],
  gon: ['^Gon'],
  zalo: ['^DMs', '^Clientes'],
  tom: ['^Tom'],
  hermes: ['^Hermes'],
}

// ── Helpers ──

function getApiKeys(env: Bindings): ApiKeyMap {
  try {
    return JSON.parse(env.PDB_API_KEYS || '{}')
  } catch {
    return {}
  }
}

function getWriterAgents(env: Bindings): string[] {
  return (env.WRITER_AGENTS || 'lisa').split(',').map(s => s.trim().toLowerCase())
}

function checkAuth(
  env: Bindings,
  ns: string,
  apiKey: string | null,
  requireWrite: boolean
): { allowed: boolean; reason?: string } {
  if (!apiKey) {
    return { allowed: false, reason: 'API key required' }
  }
  
  // Wildcard key for development
  const keys = getApiKeys(env)
  if (keys['*'] && apiKey === keys['*']) {
    return { allowed: true }
  }
  
  // Master key overrides everything
  if (env.PDB_MASTER_KEY && apiKey === env.PDB_MASTER_KEY) {
    return { allowed: true }
  }
  
  // Check namespace-specific key
  const expectedKey = keys[ns]
  if (!expectedKey) {
    return { allowed: false, reason: 'No API key configured for namespace' }
  }
  if (apiKey !== expectedKey) {
    return { allowed: false, reason: 'Invalid API key for namespace' }
  }
  
  return { allowed: true }
}

// ── App ──

export function createApp(): Hono<{ Bindings: Bindings }> {
  const app = new Hono<{ Bindings: Bindings }>()
  app.use('/*', cors())
  
  // Health
  app.get('/health', async (c) => {
    return c.json({
      ok: true,
      agent: 'pdb-edge',
      version: '0.1.0',
      timestamp: new Date().toISOString()
    })
  })
  
  // GET /v1/get/:ns
  app.get('/v1/get/:ns', async (c) => {
    const ns = c.req.param('ns')
    const subsStr = c.req.query('subs') || ''
    const subs = subsStr ? subsStr.split(',').map(s => {
      const n = Number(s)
      return Number.isInteger(n) ? n : s
    }) : []
    
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, false)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const value = await ops.get(c.env.DB, ns, subs)
    return c.json({ ok: true, value })
  })
  
  // POST /v1/set/:ns
  app.post('/v1/set/:ns', async (c) => {
    const ns = c.req.param('ns')
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, true)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const body = await c.req.json() as { subs: (string | number)[]; value: any }
    if (!body.subs) return c.json({ ok: false, error: 'subs required' }, 400)
    
    await ops.set(c.env.DB, ns, body.subs, body.value)
    return c.json({ ok: true })
  })
  
  // POST /v1/order/:ns
  app.post('/v1/order/:ns', async (c) => {
    const ns = c.req.param('ns')
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, false)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const body = await c.req.json() as { subs: (string | number)[]; direction?: number }
    const result = await ops.order(c.env.DB, ns, body.subs || [], (body.direction as 1 | -1) || 1)
    return c.json({ ok: true, result })
  })
  
  // POST /v1/data/:ns
  app.post('/v1/data/:ns', async (c) => {
    const ns = c.req.param('ns')
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, false)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const body = await c.req.json() as { subs: (string | number)[] }
    const result = await ops.data(c.env.DB, ns, body.subs || [])
    return c.json({ ok: true, result })
  })
  
  // POST /v1/kill/:ns
  app.post('/v1/kill/:ns', async (c) => {
    const ns = c.req.param('ns')
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, true)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const body = await c.req.json() as { subs: (string | number)[] }
    await ops.kill(c.env.DB, ns, body.subs || [])
    return c.json({ ok: true })
  })
  
  // POST /v1/incr/:ns
  app.post('/v1/incr/:ns', async (c) => {
    const ns = c.req.param('ns')
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, true)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const body = await c.req.json() as { subs: (string | number)[]; increment?: number }
    const result = await ops.incr(c.env.DB, ns, body.subs || [], body.increment || 1)
    return c.json({ ok: true, result })
  })
  
  // POST /v1/merge/:ns
  app.post('/v1/merge/:ns', async (c) => {
    const ns = c.req.param('ns')
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, true)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const body = await c.req.json() as {
      target_subs: (string | number)[]
      source_ns: string
      source_subs: (string | number)[]
    }
    const count = await ops.merge(
      c.env.DB, ns, body.target_subs || [],
      body.source_ns, body.source_subs || []
    )
    return c.json({ ok: true, count })
  })
  
  // GET /v1/ns/:ns/keys — list keys in namespace (pdb_ns_order equivalent)
  app.get('/v1/ns/:ns/keys', async (c) => {
    const ns = c.req.param('ns')
    const prefix = c.req.query('prefix') || undefined
    const limit = parseInt(c.req.query('limit') || '20')
    
    const apiKey = c.req.header('X-API-Key') || null
    const auth = checkAuth(c.env, ns, apiKey, false)
    if (!auth.allowed) return c.json({ ok: false, error: auth.reason }, 401)
    
    const keys = await ops.nsKeys(c.env.DB, ns, prefix, Math.min(limit, 100))
    return c.json({ ok: true, keys })
  })
  
  return app
}
