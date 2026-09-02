# 05 — Benchmark MVM Web Engine (`vm_api.py :8081`)

Fecha: 2026-08-18 · `implementations/python/pdb-sync/vm_api.py 8081`
· Requiere `lumen_mlight.dll` compilada (`cargo build --release --features
minreq` en clones frescos).

| Endpoint | Test | Resultado |
|---|---|---|
| `GET /ddp/health` | - | ✅ `{"ok": true, "ddp": "local", "hmac": false}` |
| `GET /web/saludo` | - | ✅ HTML |
| `POST /vm/execute` | `S ^X(1)="v" W "ok"` | ✅ `{"ok": true, "result": "v", "exec_ms": 127}` |
| `POST /vm/execute` | `W "mvm-ok ", $ZV` | ✅ `ok:false` con error `undefined variable: $ZV` (contrato correcto: `ok` = `not error`) |
| `GET /ddp/pull?ns=X` | - | ✅ refleja `^X(1)` persistido |

## Notas

- `ok` se calcula como `not result.get("error")` (fix `333268a`): los
  executors Rust SIEMPRE incluyen la clave `error` (None si va bien).
- El MVM escribe directo en la BD canónica (`_paths.DB_PATH`) — el
  `^X(1)="v"` del smoke test sigue en `lumen-pdb.db`.
- Los `SyntaxWarning: invalid escape sequence '\$'` de `vm_api.py` son
  preexistentes y no rompen nada.
- Si el server se queda "arrancado" pero sin escuchar: falta la DLL (está
  compilando en silencio) — ver 01-instalacion-y-correcciones.md.
