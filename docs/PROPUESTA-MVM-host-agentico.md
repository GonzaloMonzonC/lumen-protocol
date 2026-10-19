# Propuesta — la MVM como host agéntico (familia del stack)

**Fecha:** 2026-10-19 · **Repo:** `lumen-protocol` @ `d0245c85`
**Estado:** propuesta para decidir. **Nada implementado.**

---

## La pregunta

Que la MVM deje de ser "un motor que ejecuta M" y pase a ser **un host agéntico como Hermes**: un sitio donde
un agente piensa, llama tools, recuerda y deja rastro — pero corriendo nativo, soberano y con replay.

---

## Hallazgo que cambia la propuesta: **casi todo está construido**

Antes de diseñar nada, inventario real del `host.rs` (verificado, no supuesto):

### Devices cognitivos que YA existen

| device | qué hace | estado |
|---|---|---|
| `llm:call` | llamada a modelo por proveedor | ✅ |
| `llm:tools` | **tool-calling** (formato OpenAI, devuelve JSON íntegro) | ✅ DISENO-4 |
| `mcp:list` / `mcp:ping` / `mcp:tools` / `mcp:call` | **cliente MCP nativo**, JSON-RPC 2.0, registro en `^SYS("MCP",…)` con url/tipo/HMAC | ✅ 2026-09-09 |
| `rag:query` / `rag:stats` | recuperación semántica | ✅ |
| `search:text` / `search:web` | búsqueda | ✅ |
| `ddp:agent` / `ddp:push` / `ddp:pull` / `ddp:health` | federación entre nodos | ✅ |
| `tool:list` / `tool:describe` | catálogo de tools (`^TOOLS`, `^NS`, o `r:RTN`) | ✅ |
| `user:ask` | preguntar al humano | ✅ |
| `familia:accion` | ¿acciones entre agentes? | ⚠️ por verificar |
| `sys:*`, `http:*`, `json:*`, `hw:*`, `audio:*`, `cam:*` | sistema, red, utilidades | ✅ |
| `set:`, `kill:`, `ssh:`, `tcp:`, `img:` | varios | ✅ |

### Lo que YA hace un agente hoy en la MVM

`%AGENTE.m` (fuera de OSS, en `build-iso-i686/`) implementa el bucle completo:
`catálogo → llm:tools → ejecutar calls → devolver al LLM → repetir hasta MX`.

> **Conclusión incómoda pero útil: la MVM ya es un host agéntico.** No le falta motor. Le faltan
> **las tools cognitivas** (memoria, decisiones, kanban) y **la familia** (identidad, rastro, replay).

---

## El bloqueante real del paso 1 (verificado)

Parecía que la MVM podía enchufar las 117 tools hoy. **No exactamente, y hay que decirlo antes de prometerlo.**

`mcp:call` usa `mcp_http_request()` → **transporte HTTP**. Los cuatro servidores MCP del stack son **stdio**
(`read_message`/`write_message` por stdin/stdout). **No hablan entre ellos.**

Lo que sí hay:
- `thinking/server.py:4841` tiene un `do_POST` — **pero es del dashboard** (`/kanban/move`, `/metrics`,
  `/health`), **no un endpoint MCP JSON-RPC**.
- Existen `server_native.py` y `server_shm.py` por servidor — **SHM, no HTTP**.
- La MVM **sí tiene** `http:post` completo, así que **ella** puede hacer la petición. Lo que falta es **quien la
  reciba**.

### Por tanto el paso 1 real es doble

| 1a | Exponer `pdb` y `thinking` por **HTTP JSON-RPC** (un `do_POST` que reciba `tools/call`) | ~1 fichero por server |
| 1b | Registrar en `^SYS("MCP",…,"url","http")` y probar `mcp:call` desde una rutina M | configuración |

**Sin 1a, 1b no puede funcionar.** Sigue siendo barato, pero **no es "configuración y media hora"** — es un
endpoint HTTP nuevo en cada servidor. Corrijo mi propia estimación.

Nota: `poli_server.py` ya es HTTP (`:8082`), así que **hay un precedente en el repo** de server MCP por HTTP.
Se puede copiar ese patrón en vez de inventarlo.

`^TOOLS` tiene **10 utilidades de nodo** (`%SS`, `%GD`, `%WIFI`, `%NM`, `%CRON`, `%AG`, `sys:ps`, `sys:mvm`,
`audio:info`, `cam:list`). **Ninguna es cognitiva**: no hay leer memoria, no hay registrar decisión, no hay
kanban, no hay hablar con otra sesión.

**Pero** `^TOOLS(nombre,"kind")` acepta **`"mcp:server/tool"`**. Es decir:

> **Una tool de la MVM puede ser, literalmente, una tool de un servidor MCP.**

Y existe `mcp:call`. Por tanto **la MVM puede usar HOY las 117 tools de Hermes** registrando los servidores en
`^SYS("MCP",…)` y poniéndolas en `^TOOLS` con `kind = "mcp:pdb/pdb_get"`.

**Eso cambia la propuesta de sitio.** No hay que portar thinking y pdb a M. Hay que **enchufarlos**.

---

## El catálogo: 10 utilidades de nodo, ninguna cognitiva

`^TOOLS` tiene **10 entradas** (`%SS`, `%GD`, `%WIFI`, `%NM`, `%CRON`, `%AG`, `sys:ps`, `sys:mvm`,
`audio:info`, `cam:list`). **Ninguna es cognitiva**: no hay leer memoria, no hay registrar decisión, no hay
kanban, no hay hablar con otra sesión. Son `htop`, `iwconfig`, `crontab -l`.

**Pero** `^TOOLS(nombre,"kind")` acepta **`"mcp:server/tool"`** (comentario en `host.rs:1932`). Es decir: una
tool de la MVM puede ser **literalmente** una tool de un servidor MCP. Ese es el puente, y es el motivo por el
que esta propuesta es viable cuando el transporte lo sea (ver bloqueante arriba).

---

## Arquitectura propuesta: 3 capas

```
┌─────────────────────────────────────────────────────────┐
│ CAPA 3 · Familia (identidad y rastro)                   │
│   agente_id, linaje, certificado, replay                │  ← NUEVO
├─────────────────────────────────────────────────────────┤
│ CAPA 2 · Catálogo cognitivo (^TOOLS_AGENTE)             │
│   kind = "m:…" | "mcp:server/tool" | "d:device:action"  │  ← YA SOPORTADO
├─────────────────────────────────────────────────────────┤
│ CAPA 1 · Motor (lo que ya hay)                          │
│   %AGENTE.m + llm:tools + mcp:call + rag + ddp          │  ✅ EXISTE
└─────────────────────────────────────────────────────────┘
```

**El trabajo está arriba, no abajo.** La capa 1 está hecha; la 2 es configuración; la 3 es lo único nuevo.

---

## Capa 2 — el catálogo agéntico (lo que se propone)

Un `^TOOLS_AGENTE` que mezcla las tres fuentes, **con el criterio de P0-1**: pocas, las que se usan.

| # | tool | kind | por qué |
|---|---|---|---|
| 1 | `memoria_get` | `mcp:pdb/pdb_get` | leer estado |
| 2 | `memoria_has` | `mcp:pdb/pdb_has` | comprobar |
| 3 | `memoria_set` | `mcp:pdb/pdb_set` | escribir estado |
| 4 | `memoria_buscar` | `mcp:pdb/pdb_vec_search` | recuperación semántica |
| 5 | `decidir` | `mcp:thinking/decision_log` | dejar constancia |
| 6 | `suponer` | `mcp:thinking/assume` | supuestos explícitos |
| 7 | `trabajo_abrir` | `mcp:thinking/work_start` | abrir trabajo |
| 8 | `trabajo_cerrar` | `mcp:thinking/work_done` | cerrar |
| 9 | `trabajo_ver` | `mcp:thinking/work_log` | ver |
| 10 | `senal` | `mcp:thinking/state_snapshot` | diagnóstico |
| 11 | `par` | `mcp:thinking/agent_message` | hablar con otro agente |
| 12 | `buzon` | `mcp:thinking/agent_inbox` | recibir |
| 13 | `nodo_estado` | `m:%SS` | sistema (nativo, más rápido) |
| 14 | `nodo_globals` | `m:%GD` | globals |
| 15 | `web` | `d:search:web` | buscar (device nativo) |
| 16 | `rag` | `d:rag:query` | memoria semántica local |
| 17 | `humano` | `d:user:ask` | preguntar |

**17 tools, misma cifra que P0-1.** Coherencia: el agente Hermes y el agente MVM ven **el mismo catálogo
conceptual** — unos por MCP directo, otros por `mcp:call`.

> **Nombres en español** (`decidir`, `suponer`, `par`) vs los nombres técnicos del MCP. **A decidir:** mantener
> `decision_log` para que el mismo prompt valga en los dos hosts, o nombrar en español porque el MVM es soberano.
> **Recomiendo mantener los nombres técnicos**: un catálogo que se llama igual en los dos hosts permite
> portar rutinas y prompts entre ellos sin traducción.

---

## Capa 3 — la familia (lo único realmente nuevo)

Aquí está el valor y también el riesgo. **Qué significa "ser familia":**

### 3.1 Identidad verificable

```
^FAMILIA(<agente_id>,"clave_publica")   ; firma sus certificados
^FAMILIA(<agente_id>,"linaje")          ; de qué agente desciende
^FAMILIA(<agente_id>,"host")            ; "mvm:nodo-X" | "hermes:pc-desarrollo"
^FAMILIA(<agente_id>,"capacidades")     ; qué tools ve (el catálogo de la capa 2)
```

Un agente de la familia **se identifica y firma**. Eso es lo que hoy no tenemos: mis decisiones no van firmadas,
y las de `%AGENTE` tampoco.

### 3.2 Certificado de decisión (del estudio `15`)

Cada decisión deja:
```
{ agente_id, entradas, versión_reglas, versión_modelo,
  respuestas_llm_cacheadas, digest_estado, gas_used, firma }
```

**Requisito que el `19` marca como no resuelto:** el **contrato de caché LLM** (clave = prompt + modelo +
versión). Sin eso no hay replay. **Es el bloqueante real de la capa 3.**

### 3.3 Replay

`lumen replay <certificado>` re-ejecuta y compara digest. Si coincide, la decisión está probada.

**Depende de:** determinismo del MVM (existe), caché LLM (no existe), aritmética decimal (por verificar).

---

## Plan de ejecución por ROI

| # | paso | coste | gana | bloqueado por |
|---|---|---|---|---|
| **1a** | **endpoint HTTP JSON-RPC** en `pdb` y `thinking` (patrón de `poli_server.py`) | **bajo-medio** — 1 fichero por server | desbloquea todo lo demás | nada |
| **1b** | Registrar en `^SYS("MCP",…)` + probar `mcp:call` desde M | bajo — config | **la MVM ve las tools cognitivas** | 1a |
| **2** | `^TOOLS_AGENTE` con las 17 (capa 2) | bajo — datos | catálogo podado y coherente con P0-1 | 1b |
| **3** | Traer `%AGENTE.m` al repo OSS (hoy en `.gitignore`) | bajo | el bucle deja de ser invisible | decisión tuya (IPs privadas) |
| 4 | `^FAMILIA` con identidad + firma | medio | agentes identificables | — |
| 5 | Contrato de caché LLM | **alto** | habilita replay | diseño nuevo |
| 6 | Replay + digest | alto | el producto del estudio `15` | paso 5 |

**El paso 1a es la llave.** Sin endpoint HTTP no hay `mcp:call`, y sin `mcp:call` la MVM no ve ninguna tool
cognitiva. Es el único sitio donde esta propuesta puede morir — y se verifica en una tarde, no en un mes.

---

## Lo que NO propongo (y por qué)

- **No reimplementar thinking/pdb en M.** Ya existe `mcp:call`. Portar 117 tools a M sería meses de trabajo
  para tener dos implementaciones que divergen. (Excepción: las 10 de nodo, que ya son nativas y deben seguir.)
- **No tocar P0-1.** Sigue en pie: 117 → 52 en el prompt de Hermes.
- **No empezar por el replay.** Es lo más vistoso del estudio `15` y lo más caro. Sin caché LLM no existe, y
  la caché sin identidad no sirve.
- **No meter el catálogo MCP entero en `^TOOLS`.** Sería repetir el error de las 117: el valor está en las 17.

---

## Riesgos

| riesgo | probabilidad | mitigación |
|---|---|---|
| **`mcp:call` es HTTP y los servers son stdio** | **CONFIRMADO** — no es riesgo, es el bloqueante | paso 1a: endpoint HTTP. `poli_server.py` es el precedente |
| HMAC mal configurado → 401 silencioso | media | `mcp:ping` primero (initialize), como dice el propio comentario |
| El determinismo no se sostiene con LLM real | alta | es exactamente el motivo del contrato de caché (paso 5) |
| Dos catálogos divergen (`^TOOLS_AGENTE` vs MCP `agent`) | media | generar ambos de una sola fuente de verdad |
| `%AGENTE.m` fuera de OSS = el hallazgo no es reproducible por terceros | **alta** | paso 3: publicarlo o documentarlo |

---

## Lo que este documento corrige de mi propia propuesta

Dos cosas que dije y no eran verdad, verificadas antes de commitear:

1. **«`^TOOLS` está podado por diseño, refuerza P0-1»** → Falso. Son 10 utilidades de nodo, ninguna cognitiva.
   No son precedente de nada. *(corregido también en `P0-1-vs-estudio-juego.md`)*
2. **«El paso 1 es media hora de configuración»** → Falso. `mcp:call` es HTTP y los servers son stdio: hace
   falta un endpoint HTTP nuevo. Sigue siendo barato, pero **no es configuración.**

---

## La decisión que necesito

1. **¿Empezamos por el paso 1a** (endpoint HTTP JSON-RPC mínimo en `pdb`, copiando `poli_server.py`)?
   Es el que decide si todo esto es real o teórico — y hoy está **sin verificar**.
2. **¿Nombres en español o los técnicos del MCP?** Recomiendo los técnicos, para que el catálogo sea el mismo en
   los dos hosts.
3. **¿`%AGENTE.m` se publica en OSS?** Hoy está en `.gitignore` junto al taller de ISO. Sin él, "la MVM es un
   host agéntico" no lo puede verificar nadie desde fuera.

**Nada de este documento está implementado. El paso 1 no requiere escribir código de producto.**
