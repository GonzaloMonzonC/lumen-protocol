# 🚀 GUÍA: MVM Web Engine + DDP Server (`vm_api.py`)

> **Estado**: ✅ Vigente (2026-08-18) · Verificado en Windows 11 (git-bash), Python 3.11
> **Rol**: servidor HTTP local del ecosistema LUMEN — ejecuta código M en el MVM Rust, sirve el DDP (sync de namespaces) y expone rutas web/quantum/agent.
> **Puerto**: `8081` por defecto (Poli usa `8082`; vm_api no entra en conflicto).

---

## 1. Qué es

`implementations/python/pdb-sync/vm_api.py` es el **"MVM Web Engine + DDP Server"**: un `HTTPServer` (stdlib, single-threaded) que orquesta:

| Capa | Pieza | Rol |
|------|-------|-----|
| HTTP / orquestación | `vm_api.py` (Python) | endpoints REST, auth HMAC, audit, registro de rutinas |
| Motor M | `lumen_mlight.dll` (Rust, crate `implementations/rust/lumen-m-light`) | compila y ejecuta M (17μs compile, 6.4× más rápido que el evaluador Python) |
| Persistencia | SQLite PDB canónico (`_paths.DB_PATH`) | el VM escribe **directo** en SQLite vía modo `sqlite_path` |
| Fallback | `m_routines.py` / `m_light.py` (Python) | si el DLL no está disponible, degrada a StackVM Python |

El arranque registra la rutina `SALUDO^%WEB` y activa el **audit de escrituras** (`^AUDIT`): todo `S ^NS(...)=v` ejecutado por el engine queda registrado EN M (ver §7).

---

## 2. Requisitos previos

### 2.1 venv + paquete LUMEN

```bash
python -m venv .venv
.venv/Scripts/pip install -e implementations/python     # Windows
.venv/bin/pip install -e implementations/python         # macOS/Linux
```

### 2.2 ⚠️ La DLL del MVM Rust (crítico — no la saltes)

`vm_api.py` importa `lumen_mlight` (binding ctypes a la DLL). **Si la DLL no existe, el primer arranque lanza un `cargo build --release` bloqueante de ~4 minutos** que en una terminal background parece un cuelgue (no hay output hasta que termina). Compílala explícitamente la primera vez:

```bash
cd implementations/rust/lumen-m-light
cargo build --release --features minreq        # ~4 min la primera vez
# resultado: target/release/lumen_mlight.dll (Windows) / .so (Linux) / .dylib (macOS)
```

- El binding Python comprueba mtimes: si `Cargo.toml`/`src/*.rs` son más nuevos que la DLL, **vuelve a compilar** en el siguiente uso. Tras tocar Rust, recompila a mano.
- Override para apuntar a otra DLL (útil para dev): `export LUMEN_MLIGHT_LIB=/ruta/lumen_mlight.dll`
- Sin cargo o sin la DLL, el sistema **no crashea**: `available()` devuelve `False` y vm_api degrada al StackVM Python (más lento, misma API).

---

## 3. Arranque

```bash
# desde la raíz del repo
.venv/Scripts/python.exe implementations/python/pdb-sync/vm_api.py [puerto]   # Windows
.venv/bin/python implementations/python/pdb-sync/vm_api.py [puerto]           # macOS/Linux
```

Sin argumento usa `8081`. Verificación rápida:

```bash
curl http://localhost:8081/ddp/health        # → {"ok": true, "ddp": "local", "hmac": false}
curl http://localhost:8081/web/saludo        # → HTML del MVM Web Engine
```

Los `SyntaxWarning: invalid escape sequence '\$'` al arrancar son **preexistentes** (docstrings con `\$O`, `\$G`, `\$D`) — inofensivos.

---

## 4. Endpoints

| Método | Ruta | Función |
|--------|------|---------|
| GET | `/ddp/health` | estado DDP + modo HMAC |
| GET | `/ddp/pull?ns=X` | sync pull de un namespace |
| POST | `/ddp/push` | sync push (escribe en BD + audit) |
| POST | `/ddp/allocate` | alta de tarea end-to-end (Angi→KANBAN) |
| POST | `/ddp/bitacora` | bitácora DDP |
| POST | `/vm/execute` | **ejecutar código M** (ver §5) |
| POST | `/vm/register` | registrar rutina M |
| POST | `/web/register` | registrar ruta web |
| GET | `/web/<name>` | servir rutina web registrada (`SALUDO^%WEB` de demo) |
| POST | `/quantum/run` | runner quantum |
| POST | `/ddp/salon/write` | escribir `.md` en el Salón (dashboard + HMAC opcional) |
| POST | `/ddp/agent/chat` | chat A2A vía dispatcher de agentes |

---

## 5. Contrato `/vm/execute`

**Request** (JSON):

```json
{ "script": "S ^KANBAN(\"t1\")=$1 W \"ok\"", "args": ["valor"] }
```

**Flujo interno**:
1. `script` se intenta primero como **rutina nombrada** (`RoutineExecutor.exec` / `RustExecutor.exec`).
2. Si el error contiene `not found` → **fallback inline** (`exec_code`): el script se ejecuta como código M directo.
3. Backend: **Rust MVM si `available()`** (DLL), si no StackVM Python — transparente para el caller.
4. Con backend Rust, las escrituras (`S`, `K`) van **directo a SQLite** (`sqlite_path=_paths.DB_PATH`) — persisten de verdad.

**Response**:

```json
{ "ok": true, "result": "valor", "vars": {}, "error": null, "exec_ms": 39.9, "script": "..." }
```

| Campo | Significado |
|-------|-------------|
| `ok` | `true` si no hay error (⚠️ antes del fix era `false` siempre con backend Rust — ver §9) |
| `result` | último valor del stack del VM (p.ej. lo que deja un `S x=...` o `QUIT`) |
| `error` | mensaje de error del engine o `null` (⚠️ no se incluía antes del fix — fallos opacos) |
| `exec_ms` | tiempo total del handler |

**Args**: `args` → `$1..$n` + `$ZARGS` en el VM (tanto en rutinas como en inline; ⚠️ inline no los pasaba antes del fix).

**Ejemplos verificados** (Windows, git-bash — escapar comillas con `\"`):

```bash
# inline simple
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "W \"hola desde MVM!\""}'

# con args
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S ^PRUEBA(2)=$1 S ^PRUEBA(3)=$2", "args": ["tom", "smith"]}'

# rutina registrada (la demo del arranque)
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "SALUDO^%WEB"}'

# kill de namespace (limpia la prueba anterior)
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "K ^PRUEBA"}'
```

---

## 6. Auth HMAC (opcional)

- `DDP_HMAC_KEY` no configurada → **modo local**: `/ddp/health` reporta `"hmac": false` y las peticiones pasan sin firma.
- Configurada → el server exige `X-DDP-HMAC` (SHA256 del body/query según endpoint) en push/pull/raw. Fallo → `403 {"error": "HMAC auth failed"}`.

```bash
export DDP_HMAC_KEY=mi-secreto-compartido
```

> ⚠️ El **sync diario a `pdb-edge.WORKER_INTERNAL_URL` falla con 401** mientras el secreto local no coincida con el del worker Cloudflare — ver el diario 2026-08-17.

---

## 7. Audit de escrituras (`^AUDIT`)

En el arranque, `_install_engine_audit()` monkeypatchea `lumen_mlight.execute_sqlite` con `_audit_engine_write`, que **encadena el código M del registro**: cada `S ^NS(...)=v` (NS ∉ {AUDIT, WEIGHTS, CHANGES, CORDON}) ejecuta además

```
S ^AUDIT("<NS>","<ts-UTC>")=$INCREMENT(^AUDIT("<NS>","<ts-UTC>"))
```

en el MISMO engine. El registro vive en M, no en Python. Ver: `GET /ddp/...` de audit (`_audit_trail`) y el log `[VM] AUDIT-ERR: ...` si algo falla (no rompe el flujo).

---

## 8. BD canónica y `_paths.py`

Toda ruta del ecosistema resuelve desde `implementations/python/pdb-sync/_paths.py` (cero hardcode):

```
PDB_PATH (env) > PDB_DB (env) > <repo>/implementations/mcp-servers/pdb/lumen-pdb.db
```

- La BD se crea sola en el primer uso; está gitignored (`*.db`).
- `m_rust_executor` y todos los helpers usan `_paths.DB_PATH` — no tocar rutas absolutas en el código.
- La BD "memoria" vive **dentro del repo**: un `git clean`/re-clone la pierde. Para que sobreviva, exporta `PDB_PATH` a otra ubicación (p.ej. `~/pdb-data/lumen-pdb.db`).

---

## 9. Troubleshooting

| Síntoma | Causa | Solución |
|---------|-------|----------|
| Arranque "colgado" sin banner (background) | `cargo build` bloqueante porque falta la DLL | Compilar a mano (§2.2) y esperar a que termine |
| `/vm/execute` devuelve `ok:false` con `error:null` | Bug previo al fix (check de presencia de clave) | `git pull` — arreglado en el repo |
| `undefined variable: $1` en inline | Bug previo al fix (exec_code ignoraba args) | `git pull` — arreglado en el repo |
| Escrituras `^S` no persisten | Bug previo al fix (sin `sqlite_path`) | `git pull` — arreglado en el repo |
| `_audit_engine_write() got an unexpected keyword argument 'source'` | Bug previo al fix (firma estrecha del wrapper) | `git pull` — arreglado en el repo |
| `401 HMAC auth failed` en sync edge | Falta/desajuste de `DDP_HMAC_KEY` con el worker | Configurar el secreto compartido (§6) |
| `SyntaxWarning: invalid escape sequence '\$'` | Docstrings preexistentes | Inofensivo — no tocar |
| `{ok:false, error:"..."}` en `/vm/execute` | Error real del engine M (gas, sintaxis, var indefinida) | Leer el campo `error` de la respuesta |

---

## 10. Historial de fixes relevantes

| Commit | Qué arregló |
|--------|-------------|
| (2026-08-18) | `/vm/execute` con backend Rust: `ok` siempre false, error oculto, args ignorados en inline, escrituras sin persistencia, wrapper de audit incompatible con `execute_sqlite(source=...)`, `variables` descartado en el modo directo de `execute_sqlite` |
| (2026-08-17) | Eliminadas todas las rutas hardcodeadas `C:\Users\gonzalo\...` del ecosistema → `_paths.py` canónico |
|  | Sync Angi→KANBAN muerto en silencio (`_LenteConn` rompía `row_factory`) |

---

## 11. Agentes con LLM dentro del MVM (`$DEVICE("llm:call", ...)` / Smith)

**El MVM tiene LLM nativo.** Solo necesita la key en el entorno del proceso:

| Provider | Env var | Endpoint |
|----------|---------|----------|
| `deepseek` (default) | `DEEPSEEK_API_KEY` | `api.deepseek.com/v1/chat/completions` |
| `openrouter` | `OPENROUTER_API_KEY` | `openrouter.ai/api/v1/chat/completions` |
| `lingyi`/`zai`/`yi`/`01ai` | `LINGYI_API_KEY` | `api.lingyiwanwu.com` |
| `anthropic` | `ANTHROPIC_AUTH_TOKEN` | `api.z.ai/api/anthropic` |

**Contrato M** (verificado 2026-08-18 con deepseek-v4-flash):

```m
; llamada síncrona — el VM hace fork + yield + resume automáticamente
S r=$DEVICE("llm:call", prompt, system, provider, model)
; defaults: provider="deepseek", model="deepseek-v4-flash"

; fork explícito (async) → id, luego await:
S id=$DEVICE("llm:fork", prompt, system, "deepseek", "deepseek-v4-flash")
S resp=$DEVICE("llm:await", id)

; encadenar: llm:chain(parent_id, prompt, system, provider, model)
; esperar varios: llm:all("id1,id2")   ·  cancelar: llm:cancel(id)
```

**Smith — orquestación multi-agente** (fork por dominio + síntesis):

```m
S r=$DEVICE("smith:orchestrate", "mensaje", "fisica,poesia")
```

Cada dominio es un fork con identidad propia configurable en la PDB:
`^PERSONALITY("<dominio>","identity"|"provider"|"model")` — si no se define,
`identity` por defecto es "Eres un asesor experto en <dominio>..." y
provider/model = deepseek / deepseek-v4-flash. El resultado final es una
**síntesis** de todas las respuestas (verificado: 2 forks + síntesis en ~19s).

**Ejemplos curl verificados** (con `DEEPSEEK_API_KEY` en el entorno del server):

```bash
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S r=$DEVICE(\"llm:call\",\"Presentate en 1 frase\",\"Eres un agente LUMEN\") W r"}'

curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S r=$DEVICE(\"smith:orchestrate\",\"Que es la entropia?\",\"fisica,poesia\") W r"}'
```

### ⚠️ Pitfalls descubiertos en la práctica (Windows)

1. **Procesos background no heredan `export`**: al lanzar vm_api en background
   (nohup/&/gestor de procesos), el shell hijo no ve los `export` de la sesión →
   `401 Authentication Fails (auth header format should be Bearer sk-...)`.
   Pasar la key **literal en el comando**: `DEEPSEEK_API_KEY=sk-... python vm_api.py`.
2. **DLL bloqueada en Windows**: si el server está corriendo, `cargo build` falla
   con `Acceso denegado (os error 5)` porque `lumen_mlight.dll` está cargada.
   Parar el server → recompilar → relanzar.
3. **DLL obsoleta tras commits de Rust**: `ensure_built()` compara mtimes de
   `src/*.rs` contra la DLL; si el repo se actualizó, el backend degrada
   **silenciosamente** a StackVM Python y `$DEVICE` devuelve `[UNKNOWN $DEVICE]`.
   Síntoma clásico: `ok:true` pero `[UNKNOWN $DEVICE]`. Solución: recompilar.
4. **Modelos reasoning** (`deepseek-v4-flash`): agotan el presupuesto en
   `reasoning_content` y dejan `content` vacío — el MVM ya hace fallback
   automático (`reasoning_content` + `max_tokens` 8192). Para respuestas
   directas sin razonamiento, pasar `"deepseek-chat"` como modelo.
5. **Capturar el resultado**: `W $DEVICE(...)` escribe al stream de salida;
   usar `S r=$DEVICE(...)` para que el valor quede en el stack y aparezca en
   `result` de la API.
6. **UTF-8 en Windows/git-bash**: `curl -d '{"script": ..., "args": ["¿...?"]}'`
   con acentos o `¿` manda el body en la codepage de la consola y el server
   falla con `'utf-8' codec can't decode byte 0xbf ... invalid start byte`
   (el `¿` es 0xC2 0xBF). Solución: escribir el JSON a un archivo UTF-8 y usar
   `curl --data-binary @archivo.json`.

### Ejemplo completo: crear tu primer agente (SHUTTLE)

El repo incluye `implementations/python/pdb-sync/seed_agente_shuttle.py` — un
agente experto en electrónica antigua de transbordadores espaciales
(multidisciplinar: aviónica del Shuttle, AGC del Apolo, TMR/PASS-BFS,
MIL-STD-1553, historia de MUMPS y su aplicación a sistemas actuales):

```bash
# 1. sembrar identidad (^PERSONALITY) + rutina (^ROUTINE) en la PDB canónica
.venv/Scripts/python.exe implementations/python/pdb-sync/seed_agente_shuttle.py

# 2. invocarlo (server con DEEPSEEK_API_KEY en el entorno)
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  --data-binary @pregunta.json        # {"script": "SHUTTLE", "args": ["¿...?"]}

# 3. o vía Smith con su dominio (misma identidad)
#    {"script": "S r=$DEVICE(\"smith:orchestrate\",\"¿...?\",\"shuttle\") W r"}
```

**Patrón para crear tu propio agente**: escribe en la PDB
`^PERSONALITY("<dominio>","identity"|"provider"|"model")` y una rutina M en
`^ROUTINE("NOMBRE",<línea>)` cuya **primera línea sea la etiqueta de entrada**
(`NOMBRE ; comentario` — el VM Rust devuelve `unknown label` si falta) y que
llame al LLM con la pregunta como `$1`:

```m
NOMBRE ; comentario
S ident=$G(^PERSONALITY("<dominio>","identity"))
S prov=$G(^PERSONALITY("<dominio>","provider"))
S mod=$G(^PERSONALITY("<dominio>","model"))
S r=$DEVICE("llm:call",$1,ident,prov,mod)
```

La identidad se edita re-ejecutando el seed (INSERT OR REPLACE); la rutina la
lee desde `^PERSONALITY` en cada llamada — no hay que recompilar nada.

### Parto autónomo: NACER (agente que crea agentes)

`seed_agente_shuttle.py` también siembra **NACER** — el progenitor. Con la
identidad del padre (`^NACER("padre")`, default `shuttle`) como system prompt,
el LLM elige nombre+dominio del hijo, diseña su identidad y la escribe en la
PDB (^PERSONALITY + ^ROUTINE + linaje). El parto va en **dos invocaciones**
(una sola `llm:call` por invocación — ver pitfalls):

```bash
# 1) concebir: el LLM elige NOMBRE||DOMINIO
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  --data-binary @parto1.json       # {"script": "NACER", "args": ["diseno"]}
# → CONCEBIDO APOLLO (dominio: ...) — ahora invoca NACER('identidad')

# 2) nacer: diseña la identidad y escribe al hijo
curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
  --data-binary @parto2.json       # {"script": "NACER", "args": ["identidad"]}
# → NACIDO APOLLO (dominio: ...) — linaje: 1
```

El hijo recién nacido se invoca como rutina (`{"script": "NOMBRE", "args": [...]}`)
o vía Smith (`smith:orchestrate` con su dominio). Verificado en vivo 2026-08-18:
SHUTTLE engendró a **APOLLO-CORE** (experto en ingeniería de software crítico
de la era Apolo/Shuttle + MUMPS) y este respondió por su cuenta.

### ⚠️ Pitfalls del parto (verificados en la práctica)

7. **`I cond I cond` encadenados**: el runtime del MVM no los parseaba
   (`undefined variable: "x" I $F(...)`) — **arreglado en el repo** (vm.rs
   `split_if` reconoce `I`/`IF`/`F`/`FOR`/`X`/`XECUTE` como límite de cuerpo).
   Recompilar la DLL para recoger el fix.
8. **Una rutina con >1 `$DEVICE("llm:call")` secuencial + yield** → el resume
   **re-ejecuta la rutina desde el principio** (los efectos son casi
   idempotentes pero contadores/registros se ensucian). Regla: **una llamada
   LLM por invocación de rutina** — dividir el flujo en fases (como NACER).
9. **GOTO/DO a etiquetas interiores** (`G DIS`) → `unknown label DIS`: el
   dispatch de fases con `I cond G label` no funciona; usar postcondicionales
   encadenados (arreglados en 7) o rutinas separadas.
10. **Nombres de rutina con `_`** → `unknown label`: identificadores M válidos
    son solo letras, dígitos y `%`.
11. **Modelos lentos en fases largas**: deepseek-v4-flash con system prompts
    largos puede exceder el cap de yield (120s→240s en `lumen_mlight.py`).
    Para pasos de orquestación usar `deepseek-chat` explícito:
    `$DEVICE("llm:call",prompt,sys,"deepseek","deepseek-chat")`.

---

## Ver también

- [`EXTENSIBILIDAD-MVM.md`](EXTENSIBILIDAD-MVM.md) — device HTTP del MVM (F1) y fases F2/F3
- [`SSOT_ARQUITECTURA.md`](SSOT_ARQUITECTURA.md) — layered architecture (Rust = MVM, Python = binding)
- [`INDEX.md`](INDEX.md) — mapa de documentación
