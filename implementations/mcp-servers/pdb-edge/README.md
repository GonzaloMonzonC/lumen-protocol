# PDB Edge — MUMPS-style hierarchical KV store on Cloudflare D1

**TypeScript implementation** of PDB (Process Database) for Cloudflare Workers.

Port of `pdb_tools.py` (Python/SQLite) to TypeScript/D1 with the same
MUMPS-compatible subkey encoding and ^GLOBAL semantics.

## Structure

```
src/
  encode.ts      — Subkey encoding/decoding (\x02 + string + \xff)
  operations.ts  — SET/GET/ORDER/DATA/KILL/MERGE/INCR on D1
  server.ts      — Hono REST API with auth by namespace

migrations/
  0001_create_pdb_store.sql  — D1 schema

tests/           — (future)
```

## API

All endpoints require `X-API-Key` header. Write operations require the
namespace-specific key or master key.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/get/:ns?subs=a,b,c` | `$GET(^ns(a,b,c))` |
| POST | `/v1/set/:ns` | `SET ^ns(subs)=value` |
| POST | `/v1/order/:ns` | `$ORDER(^ns(subs),dir)` |
| POST | `/v1/data/:ns` | `$DATA(^ns(subs))` → 0/1/10/11 |
| POST | `/v1/kill/:ns` | `KILL ^ns(subs)` |
| POST | `/v1/incr/:ns` | `$INCREMENT(^ns(subs),n)` |
| POST | `/v1/merge/:ns` | `MERGE ^ns(target)=^source_ns(source)` |
| GET | `/v1/ns/:ns/keys` | List keys in namespace |

## Auth

- `PDB_MASTER_KEY`: Master key (full access)
- `PDB_API_KEYS`: JSON object `{"^Lisa": "key_lisa", ...}`
- `WRITER_AGENTS`: Comma-separated writer agents (default: "lisa")

## License

MIT — part of LUMEN protocol
