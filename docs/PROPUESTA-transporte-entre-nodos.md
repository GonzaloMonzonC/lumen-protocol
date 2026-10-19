# Propuesta — transporte entre nodos LUMEN (no HTTP pelado)

**Fecha:** 2026-10-19 · **Repo:** `lumen-protocol` @ `d0245c85`
**Estado:** propuesta para decidir. Nada implementado.
**Sustituye** la idea anterior de "endpoint HTTP JSON-RPC" — era la solución perezosa.

---

## Tu pregunta, respondida

> *"Me gustaría un método de comunicación entre nodos más eficiente binario — creo que ya aplicamos LUMEN
> protocol sobre el HTTP, ¿no?"*

**Sí. Y hay más de lo que recuerdas: el protocolo LUMEN binario ya está implementado en Rust y en Python.**
Pero está mal aprovechado, y ese es el problema real.

---

## Inventario verificado: qué hay de verdad

### El protocolo real (`implementations/rust/src/`)

| módulo | qué hace |
|---|---|
| **`frame.rs`** | frame LUMEN: `[LEN:Hyb128][TYPE:1B][FLAGS:1B][PAYLOAD]` — **overhead 3-7 bytes** |
| **`compress.rs`** | compresión con **diccionario estático** (JSON → binario compacto, roundtrip sin pérdida) |
| **`hyb128.rs`** | longitud variable: ≤63 → 1 byte |
| **`transport.rs`** | transporte LTA sobre streams |
| **`quic.rs`** | **QUIC (RFC 9000)**: TLS 1.3 obligatorio, 0-RTT, migración de IP, multiplexado |
| **`mux.rs`** | multiplexación de streams |
| **`datagram.rs`** | datagramas |
| **`shm.rs`** | SHM zero-copy entre procesos (mismo host) |

**Tipos de frame**: `REQUEST(0x01)`, `RESPONSE(0x02)`, `NOTIFY(0x03)`, `STREAM_DATA(0x04)`,
`SCHEMA_PATCH(0x05)`, `STREAM_INIT(0x06)`, `DICT_SYNC(0x07)`.

### Implementaciones en Python (verificadas)

| fichero | qué implementa |
|---|---|
| `implementations/mcp-servers/lumen_server.py` | **el frame Rust completo**: `_hyb128_encode` + `_build_lumen_frame` + `compress_value` |
| `implementations/python/src/lumen/shm.py` | SHM con magic `"LUME"` |
| `implementations/mcp-servers/thinking/lumen_transport.py` | WebSocket + otro framing (`LUM\x01`+zlib, el del dashboard) |

### El problema: **tres formatos distintos** conviviendo

| formato | dónde | magic | compresión |
|---|---|---|---|
| **LUMEN frame canónico** | `frame.rs` + `lumen_server.py` | **ninguno** (LEN:Hyb128 primero) | diccionario estático |
| **SHM** | `shm.rs` + `shm.py` | `0x4C554D45` "LUME" | ninguna (zero-copy) |
| **Dashboard WS** | `lumen_transport.py` | `"LUM\x01"` | **zlib** |

> **Tres linajes incompatibles entre sí.** El de `lumen_transport.py` lo dice su propio doc:
> *"passthrough for legacy JSON"* — es el que se quedó atrás.
>
> `docs/lumen-universal-protocol-strategy.md` describe el formato como *"LUM\x01 + u32 length + zlib"*,
> que es **el del dashboard, no el canónico**. La documentación estratégica está describiendo el linaje
> secundario.

---

## La propuesta: **LUMEN sobre QUIC, no sobre HTTP**

### Por qué QUIC y no HTTP

| | HTTP/1.1 o /2 con LUMEN encima | **QUIC (ya implementado)** |
|---|---|---|
| Ya existe en Rust | ❌ | ✅ `quic.rs` |
| Multiplexado sin head-of-line | ❌ (1.1) / ⚠️ (2) | ✅ nativo |
| TLS 1.3 obligatorio | ⚠️ opcional | ✅ **forzado** |
| 0-RTT (reconexión sin handshake) | ❌ | ✅ |
| Cambio de IP sin cortar (móvil/WiFi) | ❌ | ✅ |
| Streams bidireccionales por stream | ❌ | ✅ |
| Overhead de frame | HTTP headers (~200-800 B) | **3-7 B** |

**HTTP + LUMEN encima es lo peor de los dos mundos**: pagas cabeceras HTTP de texto para luego comprimir el
cuerpo. Si ya tienes `quic.rs` con TLS y multiplexado, HTTP solo añade una capa.

### El modelo de transporte por tipo de enlace

```
┌─────────────────────────────────────────────────────────────┐
│ MISMO HOST (Hermes ↔ thinking/pdb)                          │
│   SHM zero-copy · 3407 calls/s @ 0,29 ms · 0 copias         │  ✅ YA EXISTE
├─────────────────────────────────────────────────────────────┤
│ LAN / nodo ↔ nodo (MVM en casa, NAS, taller)                │
│   QUIC + LUMEN frame · TLS 1.3 · 3-7 B overhead             │  ✅ quic.rs
├─────────────────────────────────────────────────────────────┤
│ INTERNET / NAT hostil / CF Worker                           │
│   HTTP/2 o WebSocket + LUMEN frame (fallback)               │  ⚠️ parcial
└─────────────────────────────────────────────────────────────┘
```

**HTTP no desaparece: queda como *fallback* donde QUIC no pasa** (proxies corporativos, CF Workers, redes que
bloquean UDP). Pero **no es la vía principal entre nodos LUMEN**.

### Y aquí está la clave para lo que preguntabas del sistema operativo

> *"tendremos nodos lumen corriendo sobre windows o linux o mac, con nuestras versiones de lumen-os"*

Ese es **el argumento decisivo a favor de QUIC + binario**:

- **HTTP obliga a un stack de servidor** distinto en cada SO (IIS/Kestrel, nginx, launchd…). Más superficie,
  más diferencias.
- **QUIC corre sobre UDP del sistema**, y `quic.rs` es **el mismo código Rust** en las tres plataformas.
- `lumen-os` en ARM32 (neferu), x86 (taller), Windows y macOS → **un solo binario de protocolo**, no cuatro
  servidores web que configurar.
- El frame de **3-7 bytes** frente a ~200-800 de cabeceras HTTP importa en ARMv7 a 100 Mbps y en LoRa.

**Un protocolo, un binario, tres sistemas operativos.** Eso es lo que HTTP no te da.

---

## Qué habría que hacer (con lo que ya existe)

### Fase 0 — decidir el formato canónico (hoy, sin código)

**Tres linajes, uno debe ganar.** Propongo: **`frame.rs` (LEN:Hyb128 + diccionario)**.

Motivo: está en Rust (la MVM), tiene Python equivalente (`lumen_server.py`), overhead mínimo, y
`DICT_SYNC`/`SCHEMA_PATCH` ya previstos. El de `lumen_transport.py` (zlib + `LUM\x01`) es el que hay que
migrar, porque su propio código lo llama "legacy".

**Acción:** corregir `docs/lumen-universal-protocol-strategy.md`, que hoy documenta el linaje secundario.

### Fase 1 — puente MCP sobre LUMEN-QUIC

Reemplaza mi propuesta anterior (endpoint HTTP):

| pieza | qué |
|---|---|
| `pdb`/`thinking` exponen MCP por **LUMEN frame sobre QUIC** | reusar `lumen_server.py` (ya tiene el frame) + `quic.rs` |
| La MVM usa `$DEVICE("mcp:call")` **por QUIC** en vez de `mcp_http_request` | añadir rama `type="quic"` en el registro `^SYS("MCP",…)` |

El registro `^SYS("MCP",server,"type")` **ya acepta un tipo** (`"http"` por defecto). La extensión es natural:
`type = "quic"` o `"lumen"`.

### Fase 2 — fallback HTTP

Donde QUIC no pase (CF Workers, proxies), **mismo frame LUMEN sobre HTTP/2**. El frame es agnóstico al
transporte: eso ya lo permite el diseño.

---

## Lo que esto cambia de la propuesta anterior

| Antes (mi propuesta) | Ahora |
|---|---|
| "endpoint HTTP JSON-RPC en pdb/thinking" | **LUMEN frame sobre QUIC**; HTTP solo fallback |
| "media hora de configuración" | sigue siendo el cuello de botella, pero ahora **aprovecha `quic.rs`** |
| JSON en el cable | **binario con diccionario y zlib/dict** |
| 4 servidores web que mantener | **1 binario Rust** en las 3 plataformas |

---

## Medición real (esta máquina, 2026-10-19)

Con el código del repo, frame canónico + `compress_value` (diccionario):

| payload | JSON | **HTTP+JSON** | **LUMEN** | ahorro vs HTTP |
|---|---|---|---|---|
| 1 llamada `pdb_get` (123 B) | 123 B | **244 B** | **61 B** | **−75 %** |
| 5 items (570 B) | 570 B | **667 B** | **392 B** | **−41 %** |
| 50 items (5,3 KB) | 5.330 B | **5.428 B** | **3.717 B** | **−32 %** |
| 500 items (53 KB) | 53.830 B | **53.929 B** | **37.858 B** | **−30 %** |

**Dos hallazgos:**

1. **El overhead del frame LUMEN es 4 bytes** (confirmado: `Hyb128(4) + type + flags`). Las cabeceras HTTP son
   **121 bytes**. En llamadas pequeñas —que son la mayoría— el frame ahorra **el 75 %**.
2. **La compresión rinde 30-50 %**, y **más en payloads pequeños** (donde el diccionario estático brilla)
   que en grandes (donde JSON ya repite y el diccionario no gana tanto).

> **Conclusión medida:** LUMEN sobre QUIC no es una optimización teórica. En el caso dominante (llamada de
> tool pequeña) es **4 × más pequeño** que HTTP+JSON.

---

## Riesgos reales (no adornados)

| riesgo | por qué importa | mitigación |
|---|---|---|
| **`quic.rs` avisa de que el cliente NO verifica certificados** | su propio doc: *"suitable ONLY for local development"* | exige `rustls::ClientConfig` antes de producción entre nodos |
| UDP bloqueado en redes corporativas/hoteles | QUIC no pasa | fallback HTTP/2 obligatorio desde el día 1 |
| Tres linajes → si no se decide, se consolidan cuatro | ya pasó una vez | Fase 0 **antes** de escribir nada |
| `lumen_session_contract` y otros skills documentan el estado actual | pueden quedar obsoletos | actualizar tras Fase 0 |
| El formato canónico no tiene magic → no hay versionado | un peer viejo no se detecta | proponer `PROBE`/`PROBE_ACK` (ya existe `_build_probe_response`) |

---

## Decisión que necesito

1. **¿`frame.rs` es el formato canónico?** Mi recomendación sí. Si dices que sí, hay que migrar
   `lumen_transport.py` y corregir el doc de estrategia.
2. **¿QUIC como transporte principal entre nodos** y HTTP solo como fallback? Es lo que el código ya soporta.
3. **¿La MVM habla MCP por QUIC** (`^SYS("MCP",…,"type")="quic"`) o seguimos con expectativa HTTP?
4. **La medición ya está hecha** (tabla arriba). Lo que falta es tu decisión sobre el formato canónico.

**Nada de este documento está implementado.** La Fase 0 no requiere escribir código, solo decidir.