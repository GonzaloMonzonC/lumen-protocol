# EXTENSIBILIDAD — MVM (Lumen M-Light) — Acceso a Internet (F1)

> Estado: **CERRADA** — verificada E2E 2026-08-17. Verificada E2E.
> Ver también: `docs/PDB-SYNC.md`, skill `lumen-mvm-development`.

## 1. Device HTTP completo (host.rs)

La MVM (Rust, `lumen-m-light`) ahora accede a Internet con HTTP completo,
sin deuda técnica. Reemplaza el `get/post` pelado anterior (sin headers,
sin timeout, sin status).

### Llamada desde M

```
; GET con timeout
W $DEVICE("http:get","https://example.com")

; GET con headers + timeout
W $DEVICE("http:get","https://api.example.com/x","{""User-Agent"":""Mozilla/5.0""}","30")

; POST con body JSON + headers + timeout
W $DEVICE("http:post","https://tom.xxx.workers.dev/v1/fetch","{""url"":""https://example.com""}","{""x-tom-key"":""KEY""}","60")

; HEAD / PUT / DELETE — misma firma
```

### Contrato JSON de respuesta (siempre estructurado)

```json
{"status": 200, "ok": true, "body": "...", "truncated": false}
{"status": 0, "ok": false, "body": "mensaje de error del device"}
```

Campos: `status` (HTTP, 0 = fallo de red), `ok` (status 2xx/3xx), `body`
(texto o JSON serializado), `truncated` (respuesta > 200KB).

### Parámetros del device

| # | arg | descripción |
|---|-----|-------------|
| 1 | `action` | `get` \| `head` \| `post` \| `put` \| `delete` |
| 2 | `url` | URL completa |
| 3 | `body` | (solo post/put) cuerpo crudo |
| 4 | `headers` | JSON `{"Header":"valor"}` (opcional) |
| 5 | `timeout` | segundos 1–300 (opcional, default 30) |

Defaults aplicados: `User-Agent` de navegador (evita WAF 403), `Content-Type: application/json` si hay body, límite de lectura 200KB.

### SSRF guard (2026-08-18)

El device **bloquea antes de conectar** cualquier host local/privado:
`localhost`, IPs literales privadas/loopback/link-local/unspecified, y
hostnames que resuelvan (todas sus IPs) a rangos internos (protección
contra DNS → IP interna). Error claro: `HTTP: SSRF bloqueado: ...`.
minreq no sigue redirecciones automáticas → el guard se aplica por llamada.

```
$DEVICE("http:get","http://127.0.0.1:8082/health")  → error: HTTP: SSRF bloqueado: IP privada 127.0.0.1
$DEVICE("http:get","https://example.com")           → OK (público)
```

## 2. PITFALL M-LIGHT — comillas dobladas (CRÍTICO)

**El lexer M NO entiende `\"`. Las comillas dentro de un string se DOBLAN:**

```
OK    : "http:post","url","{""a"":""b""}"
FALLA : "http:post","url","{\"a\":\"b\"}"   → undefined variable
```

Al generar código M desde Python/JSON:
`body.replace('"', '""')` antes de interpolar.

## 3. Pila de investigación web GRATIS (F1)

```
M (MVM local) ──$DEVICE("http:post")──▶ Tom /v1/fetch (Worker CF, free)
                                         │ fetch nativo CF + UA navegador
                                         │ timeout 25s · límite 150KB (streaming)
                                         │ extracción texto (title + body limpio)
                                         │ mode=resume → resumen GRANITE (gratis)
                                         └──▶ {status, title, text|summary, truncated}
```

- **Tom `/v1/fetch`** — desplegado (worker `tom.*.workers.dev`, 2026-08-17).
  Body: `{url, mode: 'text'|'resume'|'raw', max_chars}`. Auth: `X-DDP-HMAC`
  o `x-tom-key` (middleware global).
- **Coste: 0 €** (plan free Workers + Workers AI).
- **Uso desde M** (verificado E2E 2026-08-17: M → Tom → Wikipedia → resumen en M).

## 4. Fases siguientes (anotadas en Angi)

- **F2** — Límites: CF free = 10ms CPU/request; separar fetch del resumen si
  hay problemas de tiempo; considerar HTMLRewriter streaming (aportación Porto).
- **F3 — XLA / device de procesos locales**: MVM lanzando procesos del SO
  (navegador, Playwright) desde código M — el `$ZF` moderno, con matiz
  *local per-ámbito* (las VMs viven en equipos locales; la PDB solo
  sincroniza datos entre núcleos dispersos). Caso de uso: XLA (X Local
  Agent, business-only) — tarea Angi registrada.
- **Seguridad Tom**: `TOM_API_KEY` del wrangler.toml local es placeholder
  (`"***"`) — poner secret real (`wrangler secret put TOM_API_KEY <real>`).

## 5. Arranque de poli_server (pitfall de procesos)

El `poli_server.py` arranca el HTTP `:8082` y LUEGO entra en el loop MCP
(stdin). **Si el stdin se cierra, el proceso muere** (y con él el HTTP).
Para lanzarlo como daemon:

```bash
tail -f /dev/null | python poli_server.py   # stdin abierto para siempre
```

(El arranque "a secas" en background puede morir en silencio al cerrarse
el stdin del padre.)
