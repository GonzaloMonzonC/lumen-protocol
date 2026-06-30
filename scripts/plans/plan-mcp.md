# Plan de mejoras para `implementations/mcp-servers`

Fecha de revision: 2026-06-17  
Ruta revisada: `implementations/mcp-servers`  
Alcance: servidores `filesystem`, `web`, `thinking`, documentacion, tests, contrato MCP/JSON-RPC, seguridad, transporte LUMEN nativo y experiencia de uso.

## Resumen ejecutivo

Las implementaciones MCP de LUMEN son valiosas como demos: muestran bien por que un protocolo binario compacto puede tener sentido alrededor de MCP, y algunas herramientas son realmente utiles para flujos de agente. `filesystem` tiene una buena base de herramientas practicas; `web` ofrece busqueda/extraccion sin API key; `thinking` explora una capa interesante de razonamiento externo.

Pero ahora mismo deberian presentarse como `demo` o `experimental`, no como reference implementations listas para uso serio. Hay cuatro problemas grandes:

1. La documentacion promete mas madurez de la que el codigo sostiene.
2. El contrato MCP/JSON-RPC es minimo y se repite en tres servidores sin validacion robusta.
3. Hay riesgos de seguridad claros, sobre todo en filesystem, web SSRF/cache y thinking state leakage.
4. Los tests declarados no son portables o no cubren lo que prometen.

La mejora mas importante no es anadir mas herramientas. Es convertir estos servidores en una base fiable: MCP comun, configuracion explicita, tests e2e, limites, sandboxing, estado por sesion y documentacion honesta.

## Estado observado

Inventario actual:

| Archivo | Lineas aproximadas | Funcion |
| --- | ---: | --- |
| `README.md` | 89 | README general de los servidores MCP |
| `TOOLS_GUIDE.md` | 174 | Guia de uso de herramientas |
| `RETROSPECTIVE.md` / `RETROSPECTIVE_ES.md` | 152 cada uno | Narrativa comparativa antes/despues |
| `filesystem/shared_tools.py` | 636 | Herramientas filesystem compartidas |
| `filesystem/server.py` | 97 | Servidor JSON-RPC stdio |
| `filesystem/server_native.py` | 165 | Servidor LUMEN binario nativo |
| `filesystem/test_roundtrip.py` | 118 | Test roundtrip nativo |
| `web/server.py` | 382 | Busqueda/extraccion web JSON-RPC stdio |
| `thinking/server.py` | 1658 | Herramientas de razonamiento/estado |
| `thinking/test_suite.py` | 267 | Test suite de thinking |
| `thinking/MEMORY_COMPARISON.md` | 112 | Comparativa con memoria Hermes |

Herramientas reales expuestas por `tools/list`:

| Servidor | Herramientas expuestas |
| --- | ---: |
| filesystem | 9 |
| web | 2 |
| thinking | 22 |
| Total | 33 |

Detalle importante: `thinking/server.py` contiene un handler `model_scan`, pero no aparece en `TOOLS`, por lo que no se anuncia en `tools/list`. Es callable si un cliente conoce el nombre, pero esta oculto para clientes normales.

## Verificaciones ejecutadas

| Check | Resultado |
| --- | --- |
| `python3 -m py_compile` sobre los `.py` | Compila sintacticamente, pero no garantiza import runtime |
| `python3 implementations/mcp-servers/filesystem/test_roundtrip.py` | Falla: `ModuleNotFoundError: No module named 'lumen'` |
| `python3 implementations/mcp-servers/thinking/test_suite.py` | Falla: ruta absoluta Windows a `C:\Users\gonzalo\...python.exe` |
| Smoke JSON-RPC `web/server.py` | `initialize` y `tools/list` responden |
| Smoke JSON-RPC `thinking/server.py` | `initialize` y `tools/list` responden |
| Smoke JSON-RPC `filesystem/server.py` | Falla en runtime con Python 3.9: `list[str] | None` no soportado en anotaciones evaluadas |

Lectura: el codigo no esta listo para prometer "reference implementation" portable. Algunas piezas funcionan en el entorno correcto, pero los tests y runtime assumptions no estan cerrados.

## Prioridades

### P0 - Bloqueante

- Hacer que los servidores arranquen en el Python soportado o documentar y exigir Python >=3.10.
- Quitar rutas absolutas de Windows de los tests.
- Corregir el servidor LUMEN nativo de filesystem.
- Anadir sandbox/limites reales a filesystem y web.
- Separar estado por sesion/cliente en thinking.
- Unificar el servidor MCP/JSON-RPC base y validar input.
- Corregir documentacion que promete MUX, streaming, wire savings y produccion sin evidencia.

### P1 - Alta

- Tests e2e para los tres servidores.
- Tests de seguridad: path escape, symlink, SSRF, redirects, cache leakage, input gigante.
- Configuracion por env documentada.
- Respuestas MCP mas estructuradas y errores normalizados.
- Rate limiting, timeouts y limites de tamano.

### P2 - Media

- Persistencia opcional y segura para thinking.
- Cache web LRU real con parametros completos.
- Busqueda filesystem con ignores, paginacion y cancelacion.
- Benchmarks reproducibles.

### P3 - Baja

- Limpieza de copy, emojis, typos, claims, BOMs y tablas.
- Mejores ejemplos de config.
- Guia de decisiones actualizada a 33 herramientas reales.

## Problemas transversales

### 1. Documentacion con claims demasiado fuertes

El README general llama a estos servidores "Reference implementations" y habla de ahorros 32-80%, multi-agent, MUX y streaming. En la practica:

- Solo `filesystem/server_native.py` intenta LUMEN nativo.
- `web` y `thinking` hablan JSON-RPC por stdio; el transporte LUMEN queda fuera.
- MUX/streaming no estan implementados realmente en los servidores MCP.
- Los benchmarks no estan ligados a scripts reproducibles.
- `filesystem/server.py` no arranca con Python 3.9 del entorno.
- Los tests declarados fallan por dependencias/rutas.

Acciones:

- Cambiar "Reference implementations" por "Experimental MCP server demos" hasta tener CI verde.
- Separar:
  - `JSON-RPC stdio demo`
  - `LUMEN wrapper compatible`
  - `LUMEN native binary`
- Poner una tabla de madurez por servidor:
  - filesystem JSON: alpha
  - filesystem native: prototype/broken until tests pass
  - web: demo
  - thinking: demo/experimental
- Mover claims de ahorro a una seccion "Benchmarks reproducibles pendientes" o enlazarlos a scripts.

Criterio de aceptacion:

- Un usuario nuevo no interpreta estos servidores como seguros/production-ready.

### 2. Inconsistencia de conteo de herramientas

Se ven varios numeros:

- README general: 33 tools.
- `TOOLS_GUIDE.md`: "18 tools across 3 servers".
- Retrospective: 18 tools, luego 28 tools.
- `thinking/README.md`: lista 7 thinking tools, pero el servidor expone 22.
- `thinking/server.py`: tiene 23 handlers si se cuenta `model_scan`, pero solo 22 schemas en `TOOLS`.

Acciones:

- Generar automaticamente una tabla de herramientas desde `TOOLS`.
- Eliminar numeros escritos a mano o marcarlos como historicos.
- Decidir si `model_scan` debe:
  - exponerse en `TOOLS`, o
  - eliminarse de `HANDLERS`, o
  - moverse detras de feature flag.

Criterio de aceptacion:

- `README.md`, `TOOLS_GUIDE.md` y `tools/list` coinciden.

### 3. Contrato MCP/JSON-RPC duplicado y minimo

Los tres servidores implementan a mano:

- `initialize`
- `tools/list`
- `tools/call`
- `notifications/initialized`

Problemas:

- No hay soporte JSON-RPC batch.
- No hay validacion de `jsonrpc == "2.0"`.
- No hay validacion de params contra schema.
- Falta error `-32602 Invalid params`.
- Una notificacion desconocida sin `id` podria recibir error, aunque las notificaciones no deben generar respuesta.
- Los errores de tool son `-32000` genericos.
- No hay logging estructurado a stderr.
- La logica esta copiada en tres archivos.

Acciones:

- Crear modulo comun `mcp_common.py`:
  - loop stdio
  - JSON-RPC parser
  - batch support
  - notification semantics
  - method dispatch
  - error helpers
  - schema validation ligera
  - logging stderr
- Cada servidor solo debe declarar:
  - server info
  - tools
  - handlers
  - config
- Tests comunes:
  - initialize
  - tools/list
  - tools/call valido
  - unknown method
  - unknown tool
  - invalid params
  - malformed JSON
  - notification without response
  - batch request

Criterio de aceptacion:

- Un cambio en el contrato MCP se arregla en un sitio, no en tres.

### 4. Falta validacion de schemas

Los `inputSchema` describen defaults, maximos y requeridos, pero el codigo no los aplica de forma sistematica. Ejemplos:

- `limit` negativo puede producir comportamiento raro.
- `paths` puede no ser lista.
- `urls` puede no ser lista.
- `work_id` puede no ser integer.
- `thought` puede ser enorme.
- `path` puede estar vacio.

Acciones:

- Implementar validador JSON Schema minimo o usar una dependencia opcional.
- Aplicar defaults antes del handler.
- Rechazar tipos incorrectos con `-32602`.
- Centralizar clamps y maximos.

Criterio de aceptacion:

- Ningun handler accede directamente a `args["x"]` sin validacion previa.

### 5. Configuracion implicita

Variables y comportamientos importantes no estan bien documentados:

- `ALLOWED_ROOTS`
- `LUMEN_BLOCKED_HOSTS`
- TTL de cache web
- ubicacion de `.work_log.json`
- maximos de lectura/busqueda
- si se permite escribir/patch

Acciones:

- Crear `CONFIG.md` o seccion comun.
- Cada servidor debe imprimir su config efectiva a stderr al arrancar.
- Diferenciar modo `demo`, `readonly`, `trusted-write`.
- Permitir desactivar herramientas peligrosas por env.

Criterio de aceptacion:

- Un operador sabe exactamente que permisos tiene cada servidor.

## Filesystem server

### 6. `filesystem/server.py` no arranca en Python 3.9

El import de `shared_tools.py` falla en Python 3.9 por anotacion `list[str] | None` evaluada en runtime sin `from __future__ import annotations`.

Acciones:

- Opcion A: exigir Python >=3.10 en docs, tests y shebang.
- Opcion B: anadir `from __future__ import annotations` en todos los `.py`.
- Opcion C: usar `Optional[list[str]]` si se quiere compatibilidad 3.9.

Criterio de aceptacion:

- `python3 implementations/mcp-servers/filesystem/server.py` arranca en el runtime documentado.

### 7. El test `filesystem/test_roundtrip.py` no es portable

Problemas:

- Inserta `C:\Users\gonzalo\...lumen-protocol\implementations\python\src`.
- Importa `server_native.py` desde `C:\Users\gonzalo\Documents\GitHub\cadencia\apps\lumen-fs`.
- No usa rutas relativas al repo.
- Falla localmente con `ModuleNotFoundError: No module named 'lumen'`.

Acciones:

- Reescribir test para:
  - resolver repo root desde `__file__`
  - insertar `../../python/src` si es necesario
  - importar `filesystem/server_native.py` local
  - ejecutarse tambien como subprocess real
- Dividir:
  - test unitario de `process_message`
  - test e2e stdio JSON
  - test e2e LUMEN frame

Criterio de aceptacion:

- `python3 implementations/mcp-servers/filesystem/test_roundtrip.py` pasa desde checkout limpio.

### 8. `server_native.py` calcula mal tamanos de frame

Se llama `build_size(payload)` como si `payload` fuese longitud. En la implementacion Python del protocolo, `build_size` espera argumentos como `frame_type` y `payload_len`; por tanto puede tratar bytes como frame type y longitud 0.

Impacto:

- Buffers mal dimensionados.
- Frames corruptos.
- El claim "pure binary frames" queda sin validar.

Acciones:

- Usar `build_size(payload_len=len(payload))` o la firma canonica correcta.
- Crear helper `build_lumen_response(frame_type, payload_dict)`.
- Probar con payloads pequenos, medianos y grandes.

Criterio de aceptacion:

- Un cliente LUMEN parsea todas las respuestas generadas por `server_native.py`.

### 9. `server_native.py` no tiene parser robusto de frames

Problemas:

- Lee 1 byte cada vez; simple pero ineficiente.
- Si `parse_frame` devuelve error, el codigo sigue acumulando bytes sin limite.
- Comprueba `hasattr(result, "needed")`, pero los parse results reales pueden usar otros nombres (`expected`, `available`).
- No hay `max_frame`.
- No hay timeout.
- No valida que el payload descomprimido sea dict JSON-RPC.

Acciones:

- Usar `FrameAssembler` de la implementacion Python si existe.
- Configurar `max_frame_bytes`.
- En parse error, responder error y resetear buffer o cerrar.
- Validar tipo de payload.
- Tests:
  - frame completo
  - frame fragmentado
  - frame demasiado grande
  - basura antes de frame
  - payload no dict

Criterio de aceptacion:

- Un input malicioso no causa acumulacion infinita de memoria.

### 10. Docs prometen MUX y Streaming en native, pero no existen

`filesystem/README.md` dice que `server_native.py` tiene MUX y Streaming. El codigo procesa un frame request y responde un frame response; no hay MUX channels ni STREAM_DATA reales.

Acciones:

- Quitar MUX/Streaming de la tabla hasta implementarlos.
- O implementar:
  - MUX open/data/close
  - stream_read sobre STREAM_DATA real
  - tests de interleaving
- Separar "tool stream_read" de "LUMEN STREAM_DATA".

Criterio de aceptacion:

- La documentacion no usa "streaming" para una paginacion que lee todo el archivo en memoria.

### 11. Sandbox de paths es buena base pero incompleto

Puntos positivos:

- Usa `Path.resolve()`.
- Verifica que la ruta resuelta este bajo roots permitidos.
- `ALLOWED_ROOTS` permite restringir.

Problemas:

- Por defecto allowed root es `os.getcwd()`, que depende de donde se lance el proceso.
- `ALLOWED_ROOTS` no hace `expanduser`.
- No hay modo read-only.
- No hay politica documentada para symlinks.
- Hay TOCTOU entre `resolve_path`, `exists`, `open`.
- Escribir sobre symlink dentro del root puede afectar destino resuelto si cambia entre validacion y open.

Acciones:

- Resolver roots al arrancar y loguearlos a stderr.
- Documentar que symlinks se siguen o se bloquean.
- Para modo seguro, rechazar symlinks en escrituras.
- Implementar `LUMEN_FS_READONLY=1`.
- Implementar `LUMEN_FS_ALLOW_WRITE=0/1`, `LUMEN_FS_ALLOW_PATCH=0/1`.
- Revalidar parent y final target justo antes de escribir.

Criterio de aceptacion:

- Tests de path escape y symlink escape pasan en macOS/Linux/Windows.

### 12. `read_file` y `stream_read` leen el archivo completo

Aunque exponen `offset`, `limit` o chunks, ambos usan `readlines()`, cargando todo el archivo en memoria.

Impacto:

- No sirve para logs enormes.
- El nombre `stream_read` es enganoso.
- Un archivo grande puede consumir mucha memoria.

Acciones:

- Implementar lectura incremental con `itertools.islice`.
- Para `stream_read`, calcular chunks sin cargar todo:
  - opcion simple: no reportar total_chunks exacto
  - opcion costosa: contar lineas con limite/indice
  - opcion avanzada: cachear offsets por archivo
- Detectar binarios.
- Limitar bytes leidos por llamada.

Criterio de aceptacion:

- Leer chunk 100 de un archivo de 1GB no carga 1GB en memoria.

### 13. `write_file` y `patch` no son atomicos

Problemas:

- Sobrescriben directamente.
- No preservan permisos/mtime.
- No hay backup.
- No hay dry-run.
- Si el proceso muere a mitad, el archivo queda corrupto.

Acciones:

- Escritura atomica con tempfile en el mismo directorio y `replace`.
- Opcion `dry_run`.
- Opcion `create_only`.
- Opcion `expected_sha256` para evitar pisar cambios concurrentes.
- En `patch`, devolver diff unificado.
- En `patch`, usar `replace(old, new, 1)` cuando `replace_all=false`.

Criterio de aceptacion:

- Fallo durante escritura no deja archivo parcial.

### 14. Busqueda regex puede hacer ReDoS y traversal enorme

`search_files` y `search_with_context` usan `re.compile(pattern)` y recorren `rglob` sin timeout.

Problemas:

- Regex catastrofica puede bloquear el proceso.
- `.git`, `node_modules`, `target`, `.venv`, `dist` no se excluyen.
- No hay limite de archivos visitados.
- No hay cancelacion.
- `search_with_context` lee cada archivo entero.

Acciones:

- Excluir directorios comunes por defecto.
- Limites:
  - max_files_scanned
  - max_bytes_scanned
  - max_file_size
  - max_runtime_ms
- Opcion `literal=true` para busquedas no regex.
- Preferir `rg` subprocess opcional cuando este disponible, con sandbox.
- Para regex stdlib, documentar limitaciones.

Criterio de aceptacion:

- Una busqueda patologica termina por limite y devuelve resultado parcial/timeout.

### 15. `list_directory` necesita paginacion y limites

Ahora lista todo el directorio y puede flood de contexto.

Acciones:

- Parametros:
  - `limit`
  - `offset`
  - `include_hidden`
  - `sort_by`
  - `recursive_depth`
- Limite de output.
- Marcar symlinks.
- Devolver tipo, size y mtime en formato estructurado opcional.

Criterio de aceptacion:

- Directorio con 100k entradas no produce respuesta gigante.

### 16. Respuestas filesystem mezclan texto bonito con datos

Las herramientas devuelven solo `content: text`. Para agentes va bien, pero se pierde estructura.

Acciones:

- Mantener texto humano.
- Anadir `data` junto a `content`:
  - `path`
  - `lines`
  - `truncated`
  - `next_offset`
  - `matches`
  - `stats`
- Hacer que los clientes puedan usar datos sin parsear texto.

Criterio de aceptacion:

- `read_file` expone `data.lines` y `data.next_offset`.

## Web server

### 17. SSRF incompleto

La proteccion actual bloquea algunos rangos privados, pero no todos los destinos no globales. Tambien valida DNS antes de `urlopen`, y `urlopen` puede resolver y seguir redirects por su cuenta.

Riesgos:

- Redirect a localhost/private.
- DNS rebinding.
- Acceso a metadata cloud.
- IPv6 link-local/multicast.
- Rangos reservados no bloqueados.

Acciones:

- Bloquear por defecto todo IP que no sea `is_global`.
- Validar cada redirect antes de seguirlo.
- Limitar redirects.
- Resolver una vez y conectar a IP validada con `Host` header, o usar opener custom.
- Bloquear:
  - loopback
  - private
  - link-local
  - multicast
  - reserved
  - unspecified
  - carrier-grade NAT
  - documentation ranges
  - IPv4-mapped IPv6 privados
- Usar puerto 443 por defecto para HTTPS en `getaddrinfo`.
- Normalizar IDNA/punycode y hostnames con punto final.

Criterio de aceptacion:

- Tests SSRF cubren localhost, 127.0.0.1, ::1, 169.254.169.254, 10/8, 172.16/12, 192.168/16, fe80::/10, redirect privado y DNS rebinding simulado.

### 18. `web_extract` lee toda la respuesta antes de truncar

`resp.read()` carga todo el body y despues hace `text[:max_chars]`.

Acciones:

- Leer por chunks hasta `max_bytes`.
- Respetar `Content-Length` y rechazar si excede.
- Limitar tamano descomprimido.
- Limitar tiempo total.
- Limitar content-encoding.

Criterio de aceptacion:

- Un servidor que envia 1GB no causa memoria excesiva.

### 19. Cache web ignora parametros relevantes

Las keys de extract son `extract:{url}`. Si una llamada pide `max_chars=1000` y otra `max_chars=30000`, la segunda puede recibir contenido truncado por la primera.

Acciones:

- Incluir en cache key:
  - url normalizada
  - max_chars
  - parser version
  - accept/content type si aplica
- Separar cache de errores de cache de exito.
- TTL configurable.
- LRU real en vez de `pop(next(iter(_cache)))`.

Criterio de aceptacion:

- Dos extracciones con distintos `max_chars` no se contaminan.

### 20. Cache "multi-agent" no es realmente compartida

El README dice multi-agent shared cache, pero `_cache` es memoria local de proceso. Si hay varios procesos, no comparten cache.

Acciones:

- Cambiar copy a "shared within one server process".
- O implementar cache persistente opcional:
  - sqlite
  - diskcache
  - archivo JSON con locks
- Incluir namespace por usuario/proyecto si hay privacidad.

Criterio de aceptacion:

- La promesa de cache coincide con la arquitectura real.

### 21. DuckDuckGo scraping es fragil

La API Instant Answer no es busqueda web general; el fallback HTML depende de clases CSS.

Acciones:

- Documentar calidad como "best effort".
- Exponer fuente de cada resultado:
  - instant_answer
  - html_fallback
  - cache
- Manejar rate limits y captchas.
- Permitir proveedor configurable.
- Tests con fixtures HTML grabados.

Criterio de aceptacion:

- Cambios de HTML no rompen silenciosamente sin test.

### 22. Extraccion HTML con regex es muy basica

Problemas:

- No decodifica entidades HTML.
- No respeta charset real.
- Puede romper con HTML malformado.
- Elimina tags con regex greedy.
- No conserva links utiles.
- No extrae metadata canonical.

Acciones:

- Si se permite dependencia: usar `html.parser` propio o `beautifulsoup4` opcional.
- Con stdlib: usar `html.parser.HTMLParser`.
- Decodificar entidades con `html.unescape`.
- Extraer:
  - title
  - h1/h2
  - canonical
  - links relevantes
  - text blocks
- Devolver `truncated`, `content_type`, `bytes_read`, `source_url`, `final_url`.

Criterio de aceptacion:

- Extraccion de fixtures HTML reales produce texto estable y legible.

### 23. Respuestas web deberian ser estructuradas

Ahora `tool_web_search` y `tool_web_extract` devuelven JSON pretty dentro de `content.text`. Esto obliga al cliente a parsear texto si quiere datos.

Acciones:

- Devolver:
  - `content` con resumen humano
  - `data` con JSON estructurado
- Incluir metadata de errores por URL.
- Marcar resultados cacheados.

Criterio de aceptacion:

- Cliente puede leer `result.data.results` sin parsear Markdown/JSON string.

### 24. Falta politica de red

Acciones:

- Config env:
  - `LUMEN_WEB_ALLOW_NETWORK=1`
  - `LUMEN_WEB_ALLOWED_DOMAINS`
  - `LUMEN_WEB_BLOCKED_HOSTS`
  - `LUMEN_WEB_MAX_BYTES`
  - `LUMEN_WEB_TIMEOUT`
  - `LUMEN_WEB_MAX_REDIRECTS`
- Modo offline para tests.
- Rate limit por host.

Criterio de aceptacion:

- En modo seguro, el servidor no hace red salvo allowlist.

## Thinking server

### 25. `thinking` mezcla muchas responsabilidades

Un solo archivo implementa:

- reasoning chains
- similarity
- contradiction
- summarization
- plan conversion
- assumptions
- project model
- model scan
- context preservation
- work log persistence
- context estimate
- servidor MCP

Acciones:

- Dividir en modulos:
  - `mcp_common.py`
  - `chains.py`
  - `similarity.py`
  - `assumptions.py`
  - `model.py`
  - `context.py`
  - `worklog.py`
  - `server.py`
- Tests por modulo.

Criterio de aceptacion:

- Cada modulo se puede probar sin arrancar servidor MCP.

### 26. Estado global sin aislamiento por sesion

Variables globales:

- `_chains`
- `_assumptions`
- `_model`
- `_preserved`
- `_works`

Riesgos:

- Un agente ve pensamientos/modelo de otro.
- Tests se contaminan.
- No hay multi-tenant.
- Reinicio borra casi todo excepto work log.

Acciones:

- Introducir `session_id` o `workspace_id`.
- Namespacing por cliente/proyecto.
- Configurar persistencia por directorio.
- Exponer `clear_session`/`export_session`/`import_session` si procede.
- Documentar retencion de datos.

Criterio de aceptacion:

- Dos clientes pueden usar thinking sin cruzar cadenas ni modelo.

### 27. `thought_bridge` no es cross-session real

Docs dicen que encuentra pensamientos de sesiones anteriores. En codigo, `_chains` vive en memoria y se pierde al reiniciar.

Acciones:

- Cambiar docs a "cross-chain in current server process".
- O persistir chains:
  - sqlite
  - JSONL append-only
  - directorio configurable
- Incluir fechas y metadata.

Criterio de aceptacion:

- Tras reiniciar servidor, `thought_bridge` encuentra chains persistidas si la feature esta activada.

### 28. Poda silenciosa de chains

`_prune_old(n=10)` elimina chains antiguas sin aviso.

Acciones:

- Configurar `max_chains`.
- Avisar cuando se poda.
- Preferir LRU con export opcional.
- No podar chains marcadas como importantes.

Criterio de aceptacion:

- El usuario sabe que una chain fue podada y puede evitarlo.

### 29. IDs predecibles y posibles colisiones

`chain_{len(_chains)+1}_{int(time.time())}` puede colisionar si se borran chains o en concurrencia.

Acciones:

- Usar UUID/ULID.
- Guardar created_at separado.

Criterio de aceptacion:

- Chain IDs no dependen del tamano actual de `_chains`.

### 30. No hay limites de input en thinking

Campos como `thought`, `statement`, `content`, `notes`, `item`, `result` pueden ser enormes.

Acciones:

- Maximos por campo:
  - thought: 8k o configurable
  - chain thoughts: 1k
  - assumptions: 500
  - model files: 5k
  - preserved items: 500
  - work items: 1k
- Rechazar o truncar explicitamente con flag `truncated`.

Criterio de aceptacion:

- Un tool call con 10MB de thought no consume memoria sin limite.

### 31. `model_scan` esta oculto pero callable

`tool_model_scan` existe y esta en `HANDLERS`, pero no aparece en `TOOLS`.

Riesgo:

- Un cliente que conozca el nombre puede invocar un scanner de filesystem que no esta documentado en el listado.
- La herramienta no usa sandbox de filesystem.

Acciones:

- Decision inmediata:
  - eliminar de `HANDLERS`, o
  - anadir schema a `TOOLS` y proteger con config.
- Si se mantiene:
  - aplicar allowed roots
  - limites de traversal
  - ignore dirs
  - symlink policy
  - `max_files`
  - `max_bytes`

Criterio de aceptacion:

- No hay handlers no anunciados salvo que sean internos e inaccesibles.

### 32. `model_scan` no usa sandbox

Usa `Path(scan_path)` directamente. Puede escanear cualquier ruta accesible por el proceso.

Acciones:

- Reusar `resolve_path` comun del filesystem o un sandbox propio.
- Denegar paths absolutos fuera de root.
- Documentar roots.

Criterio de aceptacion:

- `model_scan(path="/")` falla en modo seguro.

### 33. `model_map` ignora parametros

`root_path` y `max_depth` se leen, pero no se aplican realmente. Tambien se calcula `has_dependents` y no se usa.

Acciones:

- Filtrar por `root_path`.
- Respetar `max_depth`.
- Quitar variables muertas.
- Tests de profundidad.

Criterio de aceptacion:

- `model_map(root_path="src", max_depth=1)` cambia la salida.

### 34. `context_estimate` es inexacto

`_estimated_chars` se declara pero no se incrementa en las respuestas o inputs. Por tanto el calculo se basa casi solo en numero de tool calls.

Acciones:

- Incrementar con tamano de args y resultados.
- Incluir solo estimacion y explicar margen.
- O eliminar herramienta si da falsa precision.

Criterio de aceptacion:

- Una llamada grande aumenta la estimacion mas que una llamada pequena.

### 35. Work log persistente en directorio de codigo

`WORK_FILE` apunta a `.work_log.json` junto a `server.py`.

Problemas:

- Escribe dentro del repo/codigo.
- No hay lock.
- No hay escritura atomica.
- Errores se silencian.
- No hay separacion por usuario/proyecto.

Acciones:

- Usar `LUMEN_THINKING_STATE_DIR`.
- Escritura atomica.
- File lock.
- JSONL append-only o sqlite.
- Backups/compaction.
- Reportar errores de persistencia.

Criterio de aceptacion:

- Work log no ensucia el repo y resiste dos procesos concurrentes.

### 36. Heuristicas cognitivas pueden dar falsa autoridad

`thought_contradiction` usa similitud TF-IDF y sentimiento heuristico. `thought_evaluate` puntua por longitud, numeros y verbos. Esto puede ser util, pero no debe venderse como deteccion semantica fiable.

Acciones:

- Cambiar wording:
  - "potential contradiction heuristic"
  - "quality hints"
- Devolver `confidence` y `limitations`.
- Evitar iconografia que sugiera certeza.
- Tests con falsos positivos/negativos conocidos.

Criterio de aceptacion:

- El usuario entiende que son heuristicas, no veredictos.

### 37. Tokenizacion y clustering tienen limites

Problemas:

- Stopwords solo ingles.
- Regex limitada.
- Sin stemming/lemmatizacion.
- Clustering aglomerativo O(n^2).
- Para muchas thoughts puede ser lento.

Acciones:

- Configurar idioma.
- Stopwords ES/EN.
- Limite max thoughts por resumen.
- Algoritmo incremental o muestreo.
- Cache de vectores por chain version.

Criterio de aceptacion:

- `thought_summarize` con 1000 thoughts no bloquea el proceso sin limite.

### 38. `thought_to_plan` filtra revisiones de forma simplista

Si hay revisiones/branches complejos, puede eliminar pensamientos o dejar inconsistencias.

Acciones:

- Modelar DAG de thoughts:
  - original
  - revision
  - branch
  - active path
- Permitir `branchId` o `include_branches`.
- Tests con revision de revision y branches.

Criterio de aceptacion:

- Plan generado refleja la rama elegida.

### 39. Test suite de thinking no es portable

`thinking/test_suite.py` usa rutas absolutas Windows a Python y server.

Acciones:

- Usar `sys.executable`.
- Resolver `server.py` relativo a `__file__`.
- Capturar stderr.
- Timeout por RPC.
- Asegurar kill en finally.
- Incluir herramientas nuevas:
  - model_scan si se expone
  - work log
  - context estimate

Criterio de aceptacion:

- `python3 implementations/mcp-servers/thinking/test_suite.py` pasa en checkout local.

## Seguridad y privacidad

### 40. Filesystem write/patch son herramientas peligrosas

Acciones:

- Modo read-only por defecto recomendado.
- Confirmacion/feature flag para writes.
- Allowed roots obligatorios para writes.
- Audit log de writes y patches.

Criterio de aceptacion:

- Un despliegue sin configurar no permite escribir fuera de un sandbox explicito.

### 41. Thinking puede almacenar informacion sensible

Pensamientos, assumptions, preserved context y work log pueden contener secretos o decisiones privadas.

Acciones:

- Documentar data retention.
- Opcion de redaction simple:
  - API keys
  - tokens
  - passwords
- `clear_all` protegido.
- Export/import con aviso.
- Estado por workspace.

Criterio de aceptacion:

- El usuario sabe donde se guarda cada dato y como borrarlo.

### 42. Web cache puede filtrar informacion entre usuarios

Si varios agentes usan el mismo proceso, cache y resultados se comparten sin namespace.

Acciones:

- Namespace por client/session.
- O marcar cache como publica.
- No cachear URLs con query sensible salvo opt-in.

Criterio de aceptacion:

- Una busqueda privada de un cliente no aparece en otro contexto.

## Tests recomendados

### 43. Test matrix minima

Crear `implementations/mcp-servers/tests/` con:

- `test_mcp_common.py`
- `test_filesystem_json.py`
- `test_filesystem_native.py`
- `test_web.py`
- `test_thinking.py`
- `test_security.py`

Casos comunes:

- initialize
- initialized notification
- tools/list count
- tools/call valid
- unknown tool
- invalid params
- malformed JSON
- batch
- notification no response

### 44. Tests filesystem

- read_file offset/limit.
- read_file huge file no full memory.
- read_files max 20 and reports skipped.
- write_file atomic.
- write_file disabled in readonly.
- patch unique/multiple/dry_run.
- search_files ignores `.git`.
- regex invalid.
- regex timeout.
- symlink escape.
- ALLOWED_ROOTS with `~`.
- list_directory pagination.
- stream_read actual streaming.

### 45. Tests web

- safe URL.
- blocked localhost.
- blocked private IPv4/IPv6.
- redirect to private blocked.
- DNS rebinding fixture.
- max bytes enforced.
- cache key includes max_chars.
- non-html content.
- charset handling.
- DuckDuckGo fixture parsing.
- extract fixture HTML.

### 46. Tests thinking

- chain create/continue.
- duplicate thought numbers rejected or defined.
- revision missing target rejected.
- branch missing target rejected.
- prune behavior.
- persistence if enabled.
- session isolation.
- model_scan hidden/disabled.
- work log atomic/persistent.
- context_estimate updates chars.
- tool list equals handlers.

## Benchmarks

### 47. Benchmarks actuales no son reproducibles

Docs dan numeros como:

- `read_file`: 0.42ms
- `search_files`: 2.2ms
- thinking 30 thoughts: 4ms build, 15ms summarize
- wire savings 32-80%

Acciones:

- Crear `benchmarks/mcp_servers/`.
- Datasets:
  - small repo
  - medium repo
  - large directory
  - HTML fixtures
  - thinking chain 30/300/1000
- Output JSON con:
  - runtime
  - OS
  - Python version
  - cold/warm cache
  - bytes JSON
  - bytes LUMEN
  - p50/p95/p99
- README debe enlazar al comando.

Criterio de aceptacion:

- Cualquier claim de rendimiento se puede regenerar.

## Arquitectura propuesta

### 48. Estructura recomendada

Propuesta:

```text
implementations/mcp-servers/
  README.md
  CONFIG.md
  common/
    mcp_stdio.py
    schemas.py
    errors.py
    limits.py
    sandbox.py
  filesystem/
    server.py
    tools.py
    config.py
    tests/
  web/
    server.py
    fetcher.py
    extract.py
    config.py
    tests/
  thinking/
    server.py
    chains.py
    model.py
    worklog.py
    similarity.py
    config.py
    tests/
```

### 49. Modulo comun MCP

Debe ofrecer:

- `run_stdio_server(server_info, tools, handlers, config)`
- JSON-RPC batch.
- Notifications.
- Schema validation.
- Error mapping.
- Metrics.
- Logging stderr.
- Graceful shutdown.

### 50. Config comun

Cada servidor deberia soportar:

- `LUMEN_MCP_LOG_LEVEL`
- `LUMEN_MCP_MAX_REQUEST_BYTES`
- `LUMEN_MCP_MAX_RESPONSE_BYTES`
- `LUMEN_MCP_TIMEOUT_MS`
- `LUMEN_MCP_STATE_DIR`

Filesystem:

- `LUMEN_FS_ROOTS`
- `LUMEN_FS_READONLY`
- `LUMEN_FS_MAX_FILE_BYTES`
- `LUMEN_FS_MAX_SEARCH_FILES`

Web:

- `LUMEN_WEB_ALLOW_NETWORK`
- `LUMEN_WEB_ALLOWED_DOMAINS`
- `LUMEN_WEB_MAX_BYTES`
- `LUMEN_WEB_TIMEOUT_MS`

Thinking:

- `LUMEN_THINKING_STATE_DIR`
- `LUMEN_THINKING_PERSIST`
- `LUMEN_THINKING_MAX_CHAINS`
- `LUMEN_THINKING_MAX_THOUGHT_LEN`

## Roadmap recomendado

### Fase 0 - Honestidad y arranque

- Corregir docs `node server.py`.
- Marcar servidores como experimental/demo.
- Documentar Python version.
- Arreglar filesystem runtime en Python soportado.
- Quitar rutas absolutas de tests.
- Hacer smoke tests portables.
- Sincronizar conteo de herramientas.
- Decidir `model_scan`.

Aceptacion:

- Los tres servidores JSON-RPC arrancan y responden `tools/list`.

### Fase 1 - MCP comun y tests

- Extraer `mcp_common.py`.
- Implementar validacion params.
- Error codes correctos.
- Batch/notifications.
- Tests comunes.

Aceptacion:

- Un test suite comun pasa para filesystem, web y thinking.

### Fase 2 - Seguridad

- Filesystem readonly/sandbox/atomic writes.
- Web SSRF completo y max bytes.
- Thinking session isolation y state dir.
- Tests de seguridad.

Aceptacion:

- Casos de path escape, SSRF y cross-session leakage fallan seguro.

### Fase 3 - LUMEN native real

- Arreglar `server_native.py`.
- Usar frame assembler.
- max_frame.
- handshake consistente con protocolo.
- Tests e2e binarios.
- Quitar claims MUX/STREAM hasta implementar.

Aceptacion:

- Cliente LUMEN nativo puede usar filesystem de forma estable.

### Fase 4 - Calidad de herramientas

- `stream_read` real.
- Search con ignores/timeout.
- Web extract robusto.
- Thinking persistence opcional.
- Structured `data` en respuestas.

Aceptacion:

- Herramientas utiles para uso diario sin sorpresas grandes.

### Fase 5 - Benchmarks y publicacion

- Benchmarks reproducibles.
- Docs generadas desde resultados.
- Guias actualizadas.
- CI green badge.

Aceptacion:

- Los claims del README se pueden verificar con un comando.

## Lista corta de cambios inmediatos

Si se quieren mejoras rapidas y de alto impacto:

1. Anadir `from __future__ import annotations` o exigir Python >=3.10 en filesystem.
2. Reescribir `filesystem/test_roundtrip.py` sin rutas absolutas.
3. Reescribir `thinking/test_suite.py` con `sys.executable` y rutas relativas.
4. Corregir `server_native.py` para usar bien `build_size(payload_len=len(payload))`.
5. Quitar de docs la promesa de MUX/Streaming hasta que exista.
6. Exponer o eliminar `model_scan`.
7. Cambiar `web` cache key para incluir `max_chars`.
8. Bloquear redirects SSRF en `web`.
9. Anadir modo readonly a filesystem.
10. Extraer servidor MCP comun para no triplicar bugs.

## Conclusion

Los servidores MCP son una buena vitrina de producto, pero necesitan una capa seria de ingenieria alrededor: seguridad, limites, tests portables y una base MCP comun. La mejor decision ahora es dejar de crecer horizontalmente en numero de herramientas y endurecer las que ya existen.

El orden sano es:

1. Que arranquen y se prueben en checkout limpio.
2. Que el contrato MCP sea correcto y comun.
3. Que filesystem/web/thinking sean seguros por defecto.
4. Que LUMEN native sea realmente compatible.
5. Que los benchmarks y docs digan solo lo que se puede reproducir.

Con eso, esta carpeta puede pasar de "demo convincente" a "kit de servidores MCP aprovechable de verdad".
