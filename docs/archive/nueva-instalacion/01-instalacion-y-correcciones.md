# 01 — Instalación y correcciones

Historial completo del proceso de instalación de lumen-protocol en esta
máquina (Windows 11, usuario `gonza`), desde el 17/08/2026, con TODAS las
correcciones que hubo que hacer. Fuente: sesiones de Hermes + verificación
en repo.

---

## 17/08/2026 — Instalación inicial

1. **Reconocimiento**: no existía `lumen-protocol` en `Documents/GitHub`
   (solo `cadenceslab_com`, `ProjectOS`, `pruebaMCP`). Se clonó
   `github.com/GonzaloMonzonC/lumen-protocol`.
2. **venv**: creado `.venv/` en la raíz del repo (gitignoreado).
3. **Fix 1 — `7499c3a`** `fix(pdb): tools/list + initialize completo`:
   - `implementations/mcp-servers/pdb/server.py` no respondía a `tools/list`
     → el discovery de MCP de Hermes **se colgaba**.
   - `initialize` devolvía solo `capabilities` → pydantic del cliente Hermes
     lo rechazaba.
   - Fix: `protocolVersion` + `serverInfo` + `tools/list`.
   - `.gitignore` → excluir `.venv/`.
4. **Registro de los 4 MCP servers en Hermes** (`config.yaml`):
   `lumen-filesystem`, `lumen-web`, `lumen-thinking`, `lumen-pdb` — todos con
   el python del venv del repo.

## 17/08/2026 — Fix 2: `1d00839` — rutas canónicas (cero hardcode)

El ecosistema ya tenía su solución canónica (`_paths.py`) pero muchísimos
archivos arrastraban rutas hardcodeadas a `C:\Users\gonzalo\...` (usuario de
otra máquina). **15 archivos** corregidos:

| Componente | Archivo | Fix |
|---|---|---|
| Poli | `poli_server.py` | `PDB_SQLITE`, `POLI_CORE`, allowlist → home-relative |
| v-api | `vm_api.py` | `_LENTE_DBPATH`, `_lente_plan` → `_paths.DB_PATH` / `~` |
| Tom (registry) | `seed_agentes.py` | import vía `_paths` |
| backups/restore/lente | `backup_pdb.py`, `restore_kanban.py`, `lente_indexes.py` | → `_paths.DB_PATH` |
| tests | `test_ecosistema.py` | → `_paths.DB_PATH` |
| Rust dev scripts | `apply_all_fixes.py`, `apply_fixes.py`, `patch_all.py`, `patch_do_ref.py` | → `__file__`-relative |
| docs | `INSTALL.md`, `INSTALL_ES.md`, `HERMES_INTEGRATION.md` | ruta canónica |

**Decisión clave**: toda la memoria del ecosistema apunta a
`implementations/mcp-servers/pdb/lumen-pdb.db` (dentro del repo, gitignored
vía `*.db`). Trade-off: un `git clean`/re-clone pierde esa memoria; a cambio,
cero configuración en cualquier clone.

Jerarquía de resolución (en `pdb_tools._get_db_path()` y `_paths.py`):
```
env PDB_PATH > env PDB_DB > <repo>/implementations/mcp-servers/pdb/lumen-pdb.db
```

## 17/08/2026 — Fix 3: `333268a` — 6 bugs de `/vm/execute` (MVM)

La DLL del MVM Rust (`lumen_mlight.dll`) no existe en clones frescos
(`target/` gitignored): el primer arranque de `vm_api.py` lanza un
`cargo build --release --features minreq` (~4 min) **bloqueante y silencioso**
→ el server "arranca" pero no escucha. Compilada la DLL, arranque instantáneo.

Los 6 bugs (todos preexistentes, en `vm_api.py`, `m_rust_executor.py`,
`lumen_mlight.py`):

| # | Bug | Fix |
|---|---|---|
| 1 | `ok` se calculaba como `"error" not in result` — comprobaba **presencia de clave**, y el RustExecutor siempre incluye `error` (aunque sea `None`) → `ok:false` SIEMPRE con backend Rust | `not result.get("error")` |
| 2 | La respuesta no incluía el mensaje de error → fallos opacos | campo `error` en la respuesta |
| 3 | `_audit_engine_write` con firma estrecha → `TypeError` con el contrato completo | passthrough de `**kwargs` |
| 4 | `exec_code()` ignoraba los args → `$1`/`$2` nunca se seteaban | vars_dict igual que `exec()` |
| 5 | `exec()`/`exec_code()` usaban `execute()` sin `sqlite_path` → los `^S` no persistían | `execute_sqlite(sqlite_path=_paths.DB_PATH)` modo directo |
| 6 | El modo directo de `execute_sqlite` descartaba `variables` | incluido en el filtro de kwargs |

## 18/08/2026 — Hallazgos del benchmark (esta sesión)

### Falso positivo: "dos instancias"

`tasklist` mostraba cada server MCP duplicado (p.ej. `thinking/server.py` con
el venv Y con Python312). **No son dos instancias**: en Windows el
`venv\Scripts\python.exe` es un launcher que exec el Python base — el "hijo"
es el intérprete real del mismo server. Verificado por árbol de procesos
(`ParentProcessId`).

### Bug endémico: reconnect loop de `lumen-pdb`

- `mcp-stderr.log`: `lumen-pdb` reiniciándose cada ~8.5 min **toda la noche**
  (22:47 → 03:20, ~35 intentos).
- `errors.log`: `5 consecutive reconnects without a healthy session → parking;
  self-probe every 300s`.
- **Causa raíz**: el keepalive de Hermes manda un método al server y espera
  respuesta; `pdb/server.py` solo manejaba `initialize`/`tools/list`/
  `tools/call` y **tragaba en silencio** los desconocidos (`except: pass`) →
  timeout → reconnect → parking. El server de thinking responde a todo
  método desconocido con error JSON-RPC `-32601` → Hermes lo considera vivo.
- **Fix** (aplicado en esta sesión, `pdb/server.py`): manejar `ping`
  (resultado `{}`), `notifications/initialized` (sin respuesta) y responder a
  cualquier método desconocido con `-32601`. Verificado con handshake real:
  `initialize` → `ping` → `mystery_method` → `tools/call` ✅.

### Los MCP de ayer usaban rutas muertas

Los procesos de `thinking/filesystem/web` llevaban vivos desde el 17/08 23:01
— **cargaron el código anterior al fix `1d00839`** y resolvían la BD a
`C:\Users\gonzalo\pdb-data\lumen-pdb.db` (no existe en esta máquina) →
`PDB exists: False` → `PDB save FAILED: unable to open database file` →
todas las tools que tocan la BD fallaban (p.ej. `checklist`), mientras las de
memoria (`work_start`, `state_feeling`...) funcionaban.

**Solución**: matar los procesos MCP viejos (`taskkill /T /F`) → Hermes los
re-lanza con el código actualizado (keepalive ~8 min o reinicio de app).

### Transporte lumen ≠ MCP estándar

Los servers lumen hablan **newline-delimited JSON** sobre stdio, NO el
framing `Content-Length` del MCP estándar. Un cliente estándar se queda sin
respuesta. Además, en Windows, un proceso hijo con stdin en pipe usa **block
buffering**: `sys.stdin.readline()` no ve los datos hasta 8 KB o EOF →
los probes interactivos necesitan `PYTHONUNBUFFERED=1`.

## Checklist de arranque (resumen)

```bash
# 1. Compilar la DLL del MVM (solo clones frescos)
cd implementations/rust/lumen-m-light && cargo build --release --features minreq

# 2. Arrancar el MVM Web Engine
.venv/Scripts/python.exe -u implementations/python/pdb-sync/vm_api.py 8081

# 3. Verificar
curl http://127.0.0.1:8081/ddp/health        # {"ok": true, "ddp": "local"}
curl http://127.0.0.1:8081/web/saludo        # HTML

# 4. Probar un server MCP sin Hermes
cd docs/nueva-instalacion/tests
PYTHONUNBUFFERED=1 <venv-python> mcp_probe.py <server.py> <tool> '{"args":...}'
```
