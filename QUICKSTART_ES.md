# 🚀 LUMEN Quickstart — de cero a agentes con LLM en ~10 minutos

> **Estado**: ✅ Verificado 2026-08-18 en Windows 11 (git-bash) + Python 3.11 · comandos para macOS/Linux incluidos
> **Lo que tendrás al final**: el **MVM corriendo localmente con agentes LLM nativos** (DeepSeek / OpenRouter),
> almacenamiento persistente PDB, sync DDP — sin más cuenta que una API key de LLM.

---

## Qué es LUMEN?

**LUMEN** (*Lightweight Universal Model Exchange Network*) es un ecosistema para
computación persistente y agéntica:

| Pieza | Qué es |
|-------|--------|
| **MVM** | Una máquina virtual en Rust que ejecuta código **M** (un lenguaje pequeño y terso: `S ^KANBAN("t1")="x"`) — con **llamadas LLM nativas** (`$DEVICE("llm:call",...)`) y orquestación multi-agente (Smith) |
| **PDB** | Almacén persistente sobre SQLite: `^namespace(clave)=valor` con encoding binario, búsqueda vectorial (KNN), trail de auditoría |
| **vm_api** | El motor HTTP local (`:8081`): ejecutar M, sync DDP, dispatcher de agentes, rutas web |
| **MCP servers** | 4 servidores (120 tools) que conectan LUMEN con [Hermes Agent](https://hermes-agent.nousresearch.com) — ver `INSTALL_ES.md` |
| **Workers (opcional)** | Agentes Cloudflare Worker (tom, angi, …) alcanzables vía el dispatcher |

Todo corre **localmente** (excepto los workers opcionales). Tus datos viven en
un archivo SQLite dentro del repo (gitignored).

---

## 1. Requisitos

- **Python** 3.10+ (probado en 3.11)
- **git**
- **Toolchain de Rust** (`cargo`) — solo para compilar la DLL del MVM **una vez** (≈4 min)
- **Una API key de LLM** — DeepSeek (el default del sistema) u OpenRouter

---

## 2. Clonar + virtualenv

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

python -m venv .venv
# Windows:
.venv/Scripts/pip install -e implementations/python
# macOS / Linux:
.venv/bin/pip install -e implementations/python
```

---

## 3. Compilar el MVM (⚠️ crítico — no lo saltes)

El MVM Rust se distribuye como librería compilada (`lumen_mlight.dll` / `.so` /
`.dylib`) que **no está commiteada** en el repo. La primera vez que arranques
el motor sin ella, el inicio lanza un `cargo build` bloqueante (~4 min) que
parece un cuelgue. Compílala explícitamente:

```bash
cd implementations/rust/lumen-m-light
cargo build --release --features minreq     # ≈4 min la primera vez
cd ../../..
# resultado: target/release/lumen_mlight.dll  (Windows) / .so (Linux) / .dylib (macOS)
```

> Si luego haces `git pull` con cambios en Rust, recompila (el motor compara
> mtimes de los fuentes y degrada a un fallback Python lento si la librería
> está obsoleta — verás `[UNKNOWN $DEVICE]` en las llamadas de agente). En
> Windows, **para el server antes de recompilar** o cargo falla con "Acceso
> denegado" (la DLL está bloqueada).

---

## 4. Poner tu API key (¡nunca la commitees!)

El MVM lee la key del **entorno del proceso**:

```bash
# DeepSeek (provider/modelo por defecto: deepseek / deepseek-v4-flash)
export DEEPSEEK_API_KEY=sk-...
# o OpenRouter:
export OPENROUTER_API_KEY=sk-or-...
```

Para un setup persistente usa un archivo `.env` gitignored o tu shell rc —
**nunca** pongas la key en el repo. `*.db` ya está gitignored; añade `.env` si
lo usas. Si una key se expone alguna vez (p.ej. pegada en un chat compartido),
rótala.

---

## 5. Arrancar el motor

```bash
# Windows
.venv/Scripts/python.exe implementations/python/pdb-sync/vm_api.py 8081
# macOS / Linux
.venv/bin/python implementations/python/pdb-sync/vm_api.py 8081
```

En otra terminal, verifica:

```bash
curl http://localhost:8081/ddp/health
# → {"ok": true, "ddp": "local", "hmac": false}
```

> Los `SyntaxWarning: invalid escape sequence '\$'` del arranque son
> preexistentes e inofensivos.

> **¡Los procesos en background no heredan `export`!** Si lanzas el server en
> background (nohup, `&`, gestor de procesos), pasa la key **literal en el
> comando**: `DEEPSEEK_API_KEY=sk-... python vm_api.py 8081`. Si no, las
> llamadas de agente fallan con `401 Authentication Fails (auth header format
> should be Bearer sk-...)`.

---

## 6. Ejecutar código M

```bash
curl -s -X POST http://localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S ^MI_PRIMER_NS(1)=\"hola\" W \"escrito!\""}'
# → {"ok": true, "result": "hola", ...}

curl -s "http://localhost:8081/ddp/pull?ns=MI_PRIMER_NS"
# → {"success": true, "entries": [...], ...}
```

---

## 7. Ejecutar tu primer agente (la parte buena 🧠)

El MVM tiene **llamadas LLM nativas** — sin servicios extra:

```bash
curl -s -X POST http://localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S r=$DEVICE(\"llm:call\",\"Presentate en una frase\",\"Eres un agente LUMEN ejecutandose dentro del MVM\") W r"}'
# → {"ok": true, "result": "Soy LUMEN, un agente inteligente que opera dentro del MVM...", "exec_ms": 2400, ...}
```

**Orquestación multi-agente (Smith)** — forks en paralelo por dominio + síntesis:

```bash
curl -s -X POST http://localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S r=$DEVICE(\"smith:orchestrate\",\"Explica en 2 frases que es la entropia\",\"fisica,poesia\") W r"}'
# → una respuesta sintetizada que fusiona ambas voces (~19s)
```

Contrato LLM completo (`llm:call`, `llm:fork`, `llm:await`, `llm:chain`,
`llm:all`, `smith:orchestrate`, configuración `^PERSONALITY`, providers,
pitfalls): **[docs/GUIA_VM_API.md §11](docs/GUIA_VM_API.md)**.

> Consejo: captura los resultados con `S r=$DEVICE(...)` (asignación), no con
> `W $DEVICE(...)` — `W` escribe al stream de salida, `S` deja el valor en el
> stack y la API lo devuelve en `result`.

---

## 8. Opcional: registro de agentes + dispatcher

Siembra el registro local de agentes (17: workers Cloudflare + modos de
personalidad de Poli) y chatea vía el dispatcher:

```bash
.venv/Scripts/python.exe implementations/python/pdb-sync/seed_agentes.py   # o .venv/bin/python

curl -s -X POST http://localhost:8081/ddp/agent/chat -H "Content-Type: application/json" \
  -d '{"agente": "tom", "mensaje": "hola"}'
```

Los workers remotos exigen el secreto HMAC compartido (`DDP_HMAC_KEY` o
`x-tom-key`) que configuraste al desplegarlos; sin él responden
`{"ok":false,"error":"Se requiere X-DDP-HMAC o x-tom-key"}`. Los modos Poli
locales (`tipo: poli`) necesitan el repo `poli` aparte. Los agentes MVM del
paso 7 no necesitan **nada** de eso — corren 100% local.

---

## 9. Opcional: conectar con Hermes Agent (MCP)

LUMEN trae 4 servidores MCP (120 tools: filesystem, web, thinking, PDB).
Sigue **[INSTALL_ES.md](INSTALL_ES.md)** (o `INSTALL.md`).

---

## 10. Qué puedes construir ya

- **Agentes con personalidad** — identidad/provider/modelo por dominio:
  `S ^PERSONALITY("fisica","identity")="Eres un fisico teorico"` y luego usa
  `smith:orchestrate` (ver `GUIA_VM_API.md` §11)
- **MVM apps** — registra una app en `^APPS`, genera código M desde una
  descripción, ejecútala como proceso, forkéala, promuévela (tools PDB
  `pdb_mvm_app_*`)
- **Workflows LLM** — `llm:fork` + `llm:await` para llamadas en paralelo,
  `llm:chain` para razonamiento secuencial
- **Rutinas** — persiste rutinas M en `^ROUTINE` y llámalas por nombre
- **Internet desde M** — `$DEVICE("http:get"|"http:post", url, ...)` (F1)
- **Sync DDP** — push/pull de namespaces entre máquinas (con HMAC)
- **Rutas web** — registra rutinas M como endpoints HTTP en `:8081`

---

## Solución de problemas

| Síntoma | Causa | Fix |
|---------|-------|-----|
| El arranque "se cuelga" (sin banner) | `cargo build` de primera vez por la DLL ausente | Espera ~4 min o compila a mano (paso 3) |
| Llamada de agente devuelve `[UNKNOWN $DEVICE]` | DLL obsoleta (el repo actualizó fuentes Rust) | Recompilar (paso 3); en Windows parar el server antes |
| `401 ... should be Bearer sk-...` | La key no está en el entorno del **proceso** del server | Pasar la key literal en el comando de lanzamiento (paso 5) |
| `cargo build` → "Acceso denegado" | El server está corriendo con la DLL cargada (Windows) | Parar el server, recompilar, relanzar |
| `HMAC auth failed` (DDP/workers) | Desajuste de secreto entre local y worker | Poner el mismo `DDP_HMAC_KEY` en ambos lados |
| `'utf-8' codec can't decode byte 0xbf...` en `/vm/execute` con acentos/`¿` | El `curl -d` de git-bash en Windows manda el body en la codepage de la consola, no en UTF-8 | Escribir el JSON a un archivo UTF-8 y usar `curl --data-binary @archivo.json` |
| Errores en `/vm/execute` | Lee el campo `error` de la respuesta | Es el mensaje real del motor |
| BD "unable to open database file" | `PDB_PATH`/`PDB_DB` apunta a otro sitio | Desactivarlas o apuntar a una ruta escribible |

---

## Dónde seguir

| Doc | Contenido |
|-----|-----------|
| **[INSTALL_ES.md](INSTALL_ES.md) / [INSTALL.md](INSTALL.md)** | LUMEN + Hermes Agent (servidores MCP) |
| **[docs/GUIA_VM_API.md](docs/GUIA_VM_API.md)** | vm_api a fondo: endpoints, contrato `/vm/execute`, HMAC, audit, **agentes LLM (§11)** |
| **[docs/EXTENSIBILIDAD-MVM.md](docs/EXTENSIBILIDAD-MVM.md)** | device HTTP del MVM + roadmap F2/F3 |
| **[docs/INDEX.md](docs/INDEX.md)** | Mapa completo de documentación |
