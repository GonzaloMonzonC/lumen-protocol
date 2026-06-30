# Plan de mejoras de LUMEN — informe exhaustivo

**Autor:** Claude (Opus 4.8)
**Fecha:** 2026-06-17
**Método:** revisión línea a línea del protocolo (PAPER, RFC, SPEC) y de las cinco
implementaciones (Rust, TypeScript, Python, PHP, C#), más ejecución real de tests,
runner e2e, calculadora de costes, intento de build de TypeScript y comparación
byte a byte de la salida de TS contra los golden de Python.

> Cada ítem incluye: **dónde** (fichero:línea), **qué pasa**, **por qué importa** y
> **cómo arreglarlo**. Las severidades son: 🔴 crítico · 🟠 alto · 🟡 medio · ⚪ bajo.

---

## 0. Resumen ejecutivo y orden de ataque

El núcleo (Hyb128 + compresión por diccionario + framing) es sólido y las cinco
implementaciones coinciden entre sí. El problema es doble:

1. **La especificación (PAPER + RFC) describe un protocolo distinto del que existe en
   el código** (endianness, formato de trama, diccionario, CBOR, payloads
   estructurados, macaroons, mux, streaming).
2. **Hay defectos reales en el código**: una vulnerabilidad criptográfica grave en la
   implementación de referencia (Rust) y su gemela en TS, el build de TS roto, un
   `NameError` en el transporte WebSocket de Python, un bug de interoperabilidad con
   floats, y varias superficies de DoS sin acotar.

Orden recomendado:

| # | Bloque | Severidad | Esfuerzo |
|---|--------|-----------|----------|
| 1 | Vulnerabilidad de nonce/HKDF en crypto (Rust + TS) | 🔴 | Medio |
| 2 | Bug de interop de floats (TS) + encoding canónico | 🔴 | Bajo |
| 3 | TypeScript no compila (crypto.ts) + WebCrypto no soporta ChaCha20 | 🔴 | Medio |
| 4 | `NameError` en `LumenWebSocketTransport` (Python) | 🟠 | Trivial |
| 5 | Acotar DoS: FrameAssembler, fragmentos, Hyb128, streams | 🟠 | Medio |
| 6 | Reescribir RFC/PAPER para que describan el protocolo real | 🟠 | Alto |
| 7 | Regenerar conformance.json + harness de interop multi-lenguaje | 🟠 | Medio |
| 8 | Rendimiento del transporte Python (lectura byte a byte) | 🟡 | Bajo |
| 9 | Paridad de features entre lenguajes | 🟡 | Alto |
| 10 | Higiene de repo, LICENSE, claims (Hermes, 29 vs 18) | 🟡/⚪ | Bajo |

---

## 1. Seguridad (lo más urgente)

### 1.1 🔴 Reutilización de (clave, nonce) en ChaCha20-Poly1305 — Rust y TS

**Dónde:**
- `implementations/rust/src/crypto.rs:107-114` (`Cipher::new`)
- `implementations/rust/src/handshake.rs:316` y `:377` (`Cipher::new(&shared_secret)`)
- `implementations/typescript/src/crypto.ts:143-154` (`Cipher.init`)

**Qué pasa:** el handshake deriva un único `shared_secret` X25519 y construye **un solo
`Cipher` con esa clave cruda para ambos sentidos**. El `Cipher` cifra con `send_counter`
y descifra con `recv_counter`, **ambos arrancando en 0**. Como cliente y servidor usan
la misma clave y la misma secuencia de nonces (0,1,2…), el primer frame cliente→servidor
y el primer frame servidor→cliente se cifran con **el mismo par (clave, nonce)**.

**Por qué importa:** reutilizar (clave, nonce) en ChaCha20-Poly1305 es catastrófico:
- Reutilización de keystream → `C1 XOR C2 = P1 XOR P2` (se rompe la confidencialidad).
- Reutilización de la clave de un solo uso de Poly1305 → permite **falsificación** de tags.

Es un fallo de libro, presente en la **implementación de referencia**.

**Agravante de honestidad:** `crypto.rs:28` afirma *"Both sides derive AES-256 key via
HKDF-SHA256 from shared secret"* y el `RFC §9.4` especifica
`send_key = HKDF-Expand(shared, "lumen-send-key", 32)` /
`recv_key = HKDF-Expand(shared, "lumen-recv-key", 32)`. **No se hace ningún HKDF**; se usa
el secreto DH crudo. Es decir, el diseño correcto ya estaba escrito en el RFC pero no se
implementó.

**Cómo arreglarlo:**
1. Añadir `hkdf` + `sha2` a `Cargo.toml`. Derivar dos claves distintas:
   ```rust
   // tras derive_shared_secret
   let hk = hkdf::Hkdf::<sha2::Sha256>::new(None, &shared_secret);
   let mut send_key = [0u8; 32];
   let mut recv_key = [0u8; 32];
   // el INICIADOR usa send="c2s", recv="s2c"; el RESPONDEDOR al revés
   hk.expand(b"lumen-c2s-key", &mut c2s).unwrap();
   hk.expand(b"lumen-s2c-key", &mut s2c).unwrap();
   ```
2. Cambiar `Cipher` para tener **dos AEAD** (uno de envío, uno de recepción) con claves
   distintas, o crear dos `Cipher` (uno por sentido) con claves distintas. Así, aunque
   ambos sentidos empiecen el nonce en 0, las claves difieren y no hay reutilización.
3. Reflejar exactamente lo mismo en `crypto.ts` (`Cipher.init` debe aceptar `sendKey` y
   `recvKey` separadas, no una sola).
4. Añadir un **vector de prueba negativo** que falle si ambos sentidos comparten clave.

**Extra (endurecimiento):**
- `handshake.rs`: validar la clave pública del par contra **puntos de orden bajo** de
  X25519 (rechazar all-zero, etc.) antes de derivar; hoy no se valida (`:314`, `:375`).
- Usar comparación en tiempo constante para tags/firmas (el RFC §11.4 lo pide; verificar
  que la ruta de error de `decrypt` no filtra timing — `chacha20poly1305` ya lo hace, pero
  documentarlo).

### 1.2 🟠 Detección de replay frágil

**Dónde:** `rust/src/crypto.rs:154-157`, `ts/src/crypto.ts:214-217`.

**Qué pasa:** `if recv_nonce < recv_counter { reject }` y luego
`recv_counter = recv_nonce + 1`. Acepta saltos hacia adelante: un atacante que inyecte un
nonce muy alto (p. ej. `u64::MAX`) hace avanzar `recv_counter` y **bloquea todos los
mensajes legítimos posteriores** (DoS de sesión). Tampoco tolera reordenación legítima.

**Cómo arreglarlo:** usar una **ventana deslizante anti-replay** (estilo IPsec/DTLS): un
bitmap de los últimos N nonces vistos en torno a un máximo, en lugar de un único contador
monótono. Acota el avance y permite reordenación dentro de la ventana.

### 1.3 🔴 Macaroons: prometidos como pilar, no existen

**Dónde:** PAPER (G5, §4.7, abstract), `RFC §9.1/§9.2`, README. **Código: 0 ficheros**
(`grep -rli macaroon implementations/` no devuelve nada).

**Qué pasa:** toda la capa de "seguridad por capacidades" (tokens atenuables, caveats,
firma HMAC encadenada, código de error 0x05 "No autorizado") está documentada en detalle
y **no implementada en ningún lenguaje**.

**Cómo arreglarlo (elige una):**
- **(A) Construirlo:** una caja `lumen-macaroon` (Rust) con caveats de primera/tercera
  parte, verificación HMAC-SHA256 encadenada, y comprobación en el servidor antes de
  ejecutar `REQUEST`. Portar a TS/Python.
- **(B) Degradar el claim:** mover macaroons a una sección "Roadmap / no implementado" del
  PAPER y RFC hasta que (A) exista. **No** debe figurar como contribución entregada.

### 1.4 🟠 Handshake lee una sola vez en un buffer fijo

**Dónde:** `rust/src/handshake.rs:290-291`, `:342-343` (y `server_negotiate:64-65`):
`let mut buf=[0u8;4096]; let n=stream.read(&mut buf)?;` y se parsea **un** frame.

**Qué pasa:** se asume que el frame completo llega en una sola lectura y cabe en 4096
bytes. En un stream real (TCP/UDS) una lectura puede devolver datos parciales o varios
frames; un PROBE/ACK >4096 se trunca.

**Cómo arreglarlo:** usar el `FrameAssembler` (existe en otras impls; falta equivalente
robusto aquí) y bucle de lectura hasta tener un frame completo, con límite de tamaño.

---

## 2. Interoperabilidad entre lenguajes (rompe el claim estrella)

### 2.1 🔴 `0.0`/`1.0`/`42.0`: TypeScript los codifica como INT, el resto como FLOAT

**Dónde:** `ts/src/compress.ts:121` (`if (Number.isSafeInteger(value))`) — y el mismo
patrón en `compressedSize` (`:77`).

**Qué pasa:** en JS no se distingue `0.0` de `0`. El comentario dice *"Preserve integer vs
float distinction"* pero hace lo contrario: cualquier float de valor entero va a `TAG_INT`.

**Verificado:** comparando contra los golden de Python, el vector `float_zero` da:
```
Python      → e2 0000000000000000   (TAG_FLOAT)
TypeScript  → e3 00                 (TAG_INT)   ← divergencia
```
27/28 vectores coinciden; el que falla lo hace por esto. Es **sistémico** para todo float
de valor entero. Contradice el PAPER §6.6 ("acuerdo a nivel de byte… se decodifican de
forma idéntica").

**Bonus del mismo origen:** enteros grandes. `Number.isSafeInteger(2**60)` es `false` →
TS los manda como `TAG_FLOAT`, mientras Python/Rust mandan `TAG_INT`. Otra divergencia.

**Cómo arreglarlo (decisión de protocolo, hay que documentarla):**
- **Opción canónica recomendada:** definir en el SPEC que **el tipo se decide por el
  *valor*, no por el tipo de origen**: un número con parte fraccionaria 0 y dentro de
  rango i64 se codifica SIEMPRE como `TAG_INT` en *todas* las implementaciones. Entonces
  hay que cambiar **Python y Rust** para que `1.0`→`TAG_INT` también, y aceptar que el
  round-trip de un `float 1.0` devuelve un `int 1` (documentado).
- **Alternativa (preserva tipos):** añadir un flag/tag que distinga, pero exige que JS
  reciba la pista de tipo desde fuera (no puede inferirla). Más complejo.
- Para enteros: fijar el rango soportado a **i64** y documentar que fuera de i64 se usa
  `TAG_FLOAT` (o un tag bignum nuevo). Hoy `compress.py:_encode_zigzag_leb128` enmascara a
  64 bits silenciosamente (`& 0xFFFFFFFFFFFFFFFF`), perdiendo precisión sin avisar.

**Imprescindible:** añadir estos casos límite a `tests/e2e/shared_vectors.json`
(`float_one`, `float_42`, `int_2pow60`, `int_negzero`) — la suite actual **no** los tiene,
por eso el bug pasó desapercibido.

### 2.2 🟠 Codificaciones Hyb128 no canónicas se aceptan al decodificar

**Dónde:** todos los decoders Hyb128 (p. ej. `python/.../hyb128.py:75-97`,
`rust/.../hyb128.rs:104-141`).

**Qué pasa:** `10` puede codificarse como Tiny (1 byte) o como Short (3 bytes); el decoder
acepta ambas. El RFC dice "DEBERÍAN emitir el modo más compacto" pero no obliga a rechazar
las no mínimas.

**Por qué importa:** dos codificaciones del mismo valor → no canónico → rompe cualquier
dedupe/hash/firma sobre bytes de trama, y abre margen a evasión de filtros.

**Cómo arreglarlo:** en el SPEC, exigir codificación **mínima** y que el decoder
**rechace** representaciones no mínimas (al menos en modo estricto). Añadir vector de
conformidad negativo.

---

## 3. Build y código por lenguaje

### 3.1 🔴 TypeScript no compila — y el crypto apunta a una API inexistente

**Dónde:** `ts/src/crypto.ts`. `npm run build` → 6 errores TS (verificado con
`tsc --noEmit`, todos en `crypto.ts`). Como el build falla, **`npm test` ejecuta 0 tests**
(el glob es `dist/**/*.test.js` y `dist/` no se genera).

**Errores concretos:**
1. `crypto.ts:130` `private key: CryptoKey;` sin inicializar (TS2564). Fix: `private key!:`.
2. `crypto.ts:184` y `:221`: `{ name: "ChaCha20-Poly1305", nonce, additionalData }`. El
   campo correcto en WebCrypto AEAD es **`iv`**, no `nonce`.
3. Conflictos `SharedArrayBuffer`/`ArrayBuffer` por la versión de libs TS/Node 26.

**El problema de fondo (más grave que los tipos):** **WebCrypto NO define
`ChaCha20-Poly1305`.** El estándar W3C solo cubre AES-GCM/CTR/CBC, RSA, ECDSA, etc. Por eso
TypeScript no encuentra params con `nonce` y cae a `AesGcmParams` (que usa `iv`). Aunque
arregles los tipos, `crypto.subtle.importKey({name:"ChaCha20-Poly1305"})` y
`crypto.subtle.encrypt({name:"ChaCha20-Poly1305"})` **lanzan en runtime** en navegadores y
en el WebCrypto de Node. La cabecera dice *"Uses the Web Crypto API (… browsers)"* y
*"Mirrors the Rust crypto.rs module exactly"* — ambas afirmaciones son **falsas**.

**Cómo arreglarlo:**
- Sustituir WebCrypto por una librería real de ChaCha20-Poly1305:
  - Navegador/portable: `@noble/ciphers` (`chacha20poly1305`).
  - Node: `crypto.createCipheriv('chacha20-poly1305', key, iv, {authTagLength:16})`.
- Mantener X25519 con WebCrypto (sí existe vía Secure Curves) o también con `@noble/curves`.
- Aplicar el HKDF send/recv de §1.1.
- Añadir `tsc --noEmit` al CI para que esto no vuelva a colarse.
- Considerar correr los tests sobre las fuentes con el *type stripping* nativo de Node 26
  (`node --test src/**/*.test.ts`) en lugar de depender de `dist/`.

### 3.2 🟠 `NameError` en `LumenWebSocketTransport` — `parse_ack` sin importar

**Dónde:** `python/src/lumen/transport.py:420` usa `parse_ack(ack_data)`, pero los imports
de `negotiation` (`:34-37`) solo traen `DEFAULT_PROBE_TIMEOUT_MS` y `build_probe`.

**Qué pasa:** en cuanto el WebSocket recibe el ACK, `parse_ack` está **indefinido** →
`NameError` y la negociación revienta. La ruta nunca se ejercita en los tests (no hay test
de WebSocket).

**Cómo arreglarlo:** añadir `parse_ack` al import. Y añadir un test de
`LumenWebSocketTransport` con un servidor WS de prueba (aunque sea con `unittest.mock`).

### 3.3 🟡 Imports muertos

- `transport.py:30` importa `build_size` (no se usa).
- `negotiation.py:31` importa `build_size` (no se usa).
- Activar `ruff`/`flake8` con `F401` en CI para barrer estos casos en las 5 impls.

### 3.4 🟡 El paquete Python exige 3.10+ por un alias evaluado en import

**Dónde:** `python/src/lumen/frame.py:114`
`ParseResult = ParseComplete | ParseIncompletePayload | ParseIncomplete`.

**Qué pasa:** esto se evalúa **en tiempo de import** (no es una anotación, así que
`from __future__ import annotations` no ayuda). En 3.9 el paquete **ni siquiera importa**
(`TypeError: unsupported operand type(s) for |`). `pyproject.toml` declara `>=3.10`, así
que es coherente, pero el `classifiers` no lista 3.13/3.14.

**Cómo arreglarlo:** o usar `typing.Union[...]` para soportar 3.9, o dejar 3.10+ pero
actualizar `classifiers` y documentar el mínimo claramente. Probar en CI con 3.10–3.14.

### 3.5 🟡 `ParseError` declarado pero fuera del alias y sin emitirse

**Dónde:** `frame.py:95-96` define `ParseError`, se exporta en `__init__`, pero el alias
`ParseResult` (`:114`) **no lo incluye** y `parse_frame` nunca lo devuelve. Inconsistencia
de API: o se usa para datos malformados (p. ej. Hyb128 inválido) o se elimina.

### 3.6 ⚪ PHP en 32-bit

**Dónde:** `php/src/Hyb128.php:53` (`$value <= 0xFFFFFFFF`) y shifts. En PHP de 32-bit los
int son de 32 bits y `0xFFFFFFFF` desborda. PHP 8.5 de 64-bit va bien, pero conviene
documentar el requisito de 64-bit o usar GMP para el camino LEB128.

---

## 4. Protocolo: alinear RFC/PAPER con la realidad (o viceversa)

> Hoy el RFC y el PAPER describen un protocolo **distinto** del implementado. Todas las
> implementaciones coinciden entre sí, así que en casi todos los casos **lo que hay que
> corregir es la especificación**, no el código.

### 4.1 🟠 Endianness: la spec dice big-endian, el código es little-endian

**Dónde:** `RFC §3.1` ("Todos los enteros multibyte se transmiten en orden de red
(big-endian)") y `PAPER §4.1`. El **Apéndice A** del RFC da pseudocódigo big-endian
(`[0x80 | (value>>16)&0x3F, (value>>8)&0xFF, value&0xFF]`).
El código en las 5 impls es **little-endian** (`struct.pack_into("<H")`, `to_le_bytes()`,
`WriteU16LE`, `chr($value & 0xFF)` primero).

**Verificado:** `hyb128(64)` produce `80 40 00` (LE). El Apéndice A produciría `80 00 40`.

**Cómo arreglarlo:** reescribir `RFC §3.1`, `PAPER §4.1` y el **Apéndice A** a
little-endian. Es lo más barato (5 impls ya están de acuerdo en LE).

### 4.2 🟠 Formato de trama: `DICT_REF` no existe; `LEN` mide solo el payload

**Dónde:** `RFC §3.1` y Figura 1 incluyen un campo `DICT_REF` tras `FLAGS` cuando
`COMPRESSED`, y dicen `LEN = longitud total de la trama`.
El código no tiene `DICT_REF` (`frame.py`, `frame.rs:1-11`) y `LEN = longitud del payload`
("Hyb128 encodes PAYLOAD length only").

**Realidad de la compresión:** no hay `DICT_REF` a nivel de trama; las referencias de
diccionario van **dentro del payload** (`TAG_STR_DICT 0xE4 <id>` para valores y el `id`
directo como clave de objeto). La compresión es por-string/por-clave, no por-trama.

**Cómo arreglarlo:** eliminar `DICT_REF` del RFC §3.1/§3.3/Figura 1, corregir `LEN` a
"longitud del payload", y reescribir §6 describiendo el esquema real de tags 0xE0–0xE7 +
ids de diccionario embebidos.

### 4.3 🟠 "CBOR" no es CBOR

**Dónde:** `RFC §5.1/§5.2/§5.3` ("args … CBOR"), `PAPER §8` ("LUMEN utiliza CBOR para la
representación de los valores de argumento opacos").
El código implementa un formato **propio** (`compress.rs`/`compress.py`/`compress.ts`) con
tags `0xE0..0xE7`. **No es CBOR** (en CBOR esos bytes son otra cosa).

**Cómo arreglarlo:** o (A) decir la verdad — "codificación compacta propia de LUMEN",
documentando los tags — o (B) migrar de verdad a CBOR (`ciborium` en Rust, `cbor2` en
Python, etc.) y reescribir las tres impls. (A) es lo honesto y barato; (B) ganaría
ecosistema pero es trabajo grande.

### 4.4 🟠 Diccionario estático del RFC ≠ diccionario del código

**Dónde:** `RFC §6.1` mapea **nombres de método**:
`0x00=tools/list, 0x01=tools/call, 0x02=prompts/get …`
El código (`dict.py:32-47`, idéntico en las otras impls) mapea **claves de campo**:
`0x00=tool, 0x01=arguments, 0x02=result, 0x03=error, 0x04=id …`

**Por qué importa:** un `id=0x00` significa "tools/list" según el RFC y "tool" según el
código. Son tablas irreconciliables. (Nota: `conformance.json` usa la tabla del código, no
la del RFC.)

**Cómo arreglarlo:** publicar en el RFC la tabla **real y completa** de 128 entradas
(volcada desde `dict.rs`/`dict.py`), y versionarla (cualquier cambio = nueva versión de
protocolo, como ya dice §10.3). Hoy el RFC solo lista 14 entradas y encima equivocadas.

### 4.5 🟠 Payloads estructurados de REQUEST/RESPONSE no implementados

**Dónde:** `RFC §5.1` define REQUEST como
`request_id(4B) + timeout_ms(2B) + method_len + method + args(CBOR)`, y `§5.2` RESPONSE con
`request_id(4B) + status_code(1B) + payload`. `§5.4` STREAM_DATA, `§5.6` STREAM_INIT, etc.
El código trata el payload como **bytes opacos** (el resultado de `compress_value(message)`
del mensaje JSON-RPC entero). No hay `request_id`, `timeout_ms`, `status_code`, ni los
campos de stream.

**Por qué importa:** la correlación, los timeouts y los códigos de estado del RFC §5.2
(0x01 método no encontrado, 0x05 no autorizado…) son **inalcanzables** porque no están en
el wire. La capacidad de saltar/enrutar tramas por `request_id` tampoco.

**Cómo arreglarlo:** decidir el modelo y cumplirlo. O (A) implementar los encabezados
estructurados por tipo de trama (más trabajo, pero habilita correlación/timeouts/errores
nativos), o (B) documentar que LUMEN v1 transporta el mensaje JSON-RPC comprimido como
payload opaco y mover §5.1–§5.6 a "previsto". Sin esto, medio RFC es ficción.

### 4.6 🟠 Streaming nativo (§7) y Multiplexación (§8): solo constantes

**Dónde:** `STREAM_INIT/STREAM_DATA` y `MUX` existen como **constantes de tipo**
(`frame.rs:24,28,34`) pero no hay builders/parsers del payload estructurado ni lógica de
canales (OPEN/DATA/CLOSE/PAUSE/RESUME del §5.9/§8). Sí existe control de flujo
(`TYPE_FLOW_CTL 0x0E`, `FlowCtl`) **solo en Rust**.

**Cómo arreglarlo:** implementarlos de verdad (al menos en Rust) o marcarlos como no
implementados en RFC/PAPER. El claim del PAPER de "<50 µs de latencia de streaming" no es
sostenible si el streaming tal como se describe no existe.

### 4.7 🟡 Negociación: PROBE/PROBE_ACK con JSON, no el TRANSPORT_INIT del RFC

**Dónde:** `RFC §5.11` define la negociación con `TRANSPORT_INIT(0x0B)`/
`TRANSPORT_ACK(0x0C)` y campos binarios (`version`, `levels_mask`, `heartbeat_ms`,
`max_frame`). El código Python/TS usa `PROBE(0x0F)`/`PROBE_ACK(0x10)` con un dict
JSON-ish (`{protocol, version, client_name}`) comprimido. En Rust **conviven ambos**
(`handshake.rs`: `server_negotiate` usa TRANSPORT_INIT con `{"caps":[...]}`, y
`*_encrypted_handshake` usa PROBE con `{v,caps,pk}`).

**Cómo arreglarlo:** unificar **un** mecanismo de handshake y documentarlo con el formato
de payload exacto (binario o JSON, pero uno). Hoy hay tres variantes.

### 4.8 🟡 Boilerplate IETF falso y metadatos incoherentes

**Dónde:** `RFC_LUMEN(_ES).md` cabecera y "Estado de Este Memorándum".

- Dice *"Representa el consenso de la comunidad IETF… aprobado para publicación por el
  IESG"*, `ISSN: 2070-1721`, `Category: Standards Track`. **No es un RFC del IETF.**
  Presentarlo así es engañoso.
- Fechas incoherentes: cabecera "15 Junio 2026"; `[SPEC_DEV]` 2025; `conformance.json`
  "generated 2025-01-17"; `Apéndice C` dice Python "Beta", PHP "extensión Swoole"
  (el código PHP es puro, sin Swoole), C# "paquete NuGet" (no hay paquete publicado).
- Apéndice B: el ejemplo "B.1" (`07 01 00 …`) empieza con `LEN=07` pero muestra ~20 bytes;
  no cuadra ni con su propio formato.

**Cómo arreglarlo:** convertir el documento en un "Draft / White Paper" honesto (quitar el
boilerplate IESG/ISSN/Standards Track o marcarlo claramente como `Independent Submission /
draft`), unificar fechas, corregir el Apéndice C al estado real (ver §9) y rehacer los
ejemplos del Apéndice B desde el código.

---

## 5. Robustez / DoS (el propio RFC §11.3 los lista; el código no los aplica)

### 5.1 🟠 `FrameAssembler` sin tope de buffer

**Dónde:** `python/src/lumen/frame_assembler.py:32-55` (y equivalentes TS/PHP).

**Qué pasa:** `push` hace `self._buf.extend(chunk)` sin límite. Un peer que envíe un Hyb128
con `LEN` enorme (hasta 4 GB en u32, arbitrario en LEB128) o que nunca complete un frame
hace crecer el buffer sin fin → agotamiento de memoria.

**Cómo arreglarlo:** aplicar `max_frame` (negociado en el handshake; el RFC §11.3 lo exige)
y un tope de buffer pendiente; al superarlo, error/cierre. Validar `payload_len` contra
`max_frame` en `parse_frame` antes de esperar más bytes.

### 5.2 🟡 `FrameAssembler` es O(n²) con la lectura byte a byte

**Dónde:** `frame_assembler.py:38-53` + `transport.py:241-243,337-339`.

**Qué pasa:** el transporte lee **1 byte cada vez** (`self._process.stdout.read, 1`) y
llama a `push` por byte; `push` reparsa desde offset 0 cada vez, y `del self._buf[:consumed]`
desplaza el bytearray (O(n)). Para un frame de N bytes → O(N²). Contradice el "zero-copy".

**Cómo arreglarlo:** leer en bloques (p. ej. 64 KiB), llevar un offset de consumo en vez de
`del self._buf[:consumed]` por frame, y compactar el buffer perezosamente.

### 5.3 🟡 Reensamblaje de fragmentos sin acotar

**Dónde:** `RFC §5.1`/§4.3 (flag FRAGMENTED, `message_id`, `fragment_seq/count`). No veo
implementación de reensamblaje con límites de búfers concurrentes ni timeout (RFC §11.3
recomienda acotarlos). Si se implementa, debe nacer con esos límites.

### 5.4 🟡 Tope de contenedores en `decompress` muy bajo y silencioso

**Dónde:** `compress.py:45` `_MAX_COUNT = 1024` y `:236,248` `count = min(count, _MAX_COUNT)`.

**Qué pasa:** un objeto/array legítimo con >1024 elementos se **trunca silenciosamente** al
descomprimir (pérdida de datos sin error). A la vez, no protege de verdad porque el atacante
controla el stream de tags igualmente.

**Cómo arreglarlo:** subir/parametrizar el límite, y ante exceso **fallar** (no truncar).
Verificar que el `count` declarado es coherente con los bytes restantes.

---

## 6. Tests, conformidad y CI

### 6.1 🟠 `conformance.json` no corresponde al código

**Dónde:** `tests/e2e/conformance.json`.

- Sus vectores Hyb128 describen un esquema 1/2/4 bytes (`64→"4040"`); el código produce
  1/3/5 (`64→"804000"`, verificado). Tabla de divergencias:

  | Valor | conformance.json | Código real |
  |-------|------------------|-------------|
  | 64 | `4040` | `804000` |
  | 16383 | `7fff` | `80ff3f` |
  | 16384 | `80004000` | `800040` |
  | u32max | `80ffffff` | `c0ffffffff` |

- Declara `cross_impl_results.rust = {passed:94}` contra vectores que el código no puede
  generar, y `typescript = null`. No es un resultado real reproducible.
- Lista categorías (`batch`, `flow_ctl`, `quic`, `crypto`, `handshake`) que solo existen en
  Rust → da impresión de cobertura uniforme inexistente.

**Cómo arreglarlo:** **generar** `conformance.json` desde el código (no a mano), por
categoría y por implementación, y rellenar `passed/failed` ejecutando de verdad cada
runner. Si una categoría no aplica a una impl, marcarla `n/a`, no omitir.

### 6.2 🟠 Falta un harness de interop multi-lenguaje en CI

**Dónde:** existe la idea (`shared_vectors.json` + golden; `ts/src/e2e.test.ts` lee los
golden de Python) pero **no se ejecuta**: el build de TS está roto (§3.1) y no hay workflow
que cruce las 5 impls.

**Cómo arreglarlo:** un job de CI que:
1. Genere golden con Python.
2. Verifique byte a byte que Rust, TS, PHP y C# producen lo mismo y decodifican los golden.
3. Falle el PR ante cualquier divergencia.
Esto habría atrapado el bug de floats (§2.1) automáticamente.

### 6.3 🟡 Ampliar vectores con casos límite

Añadir a `shared_vectors.json`: `float_one`, `float_minus_zero`, `int_2pow53`,
`int_2pow60`, claves no-ASCII, objetos profundamente anidados, arrays >1024, strings con
longitud en frontera Hyb128 (63/64/65535/65536), y entradas malformadas (para los decoders).

### 6.4 🟡 Tests ausentes señalados arriba

- WebSocket transport Python (§3.2).
- Vector negativo de nonce/clave compartida (§1.1).
- `tsc --noEmit` y `ruff`/`clippy`/`dotnet build` en CI para las 5 impls.

---

## 7. Rendimiento (coherencia con los claims)

### 7.1 🟡 Transporte Python lee 1 byte a la vez vía threadpool

**Dónde:** `transport.py:241-243` y `:337-339`
(`await loop.run_in_executor(None, self._process.stdout.read, 1)`).

**Qué pasa:** un viaje al threadpool **por byte**. Para un protocolo que presume de
rendimiento, esto es lentísimo y domina la latencia real en Python.

**Cómo arreglarlo:** leer en bloques con un reader dedicado (o `asyncio` connect_read_pipe);
el comentario justifica el byte-a-byte por "pipes de Windows", pero la solución correcta es
leer `read(N)` no bloqueante / en hilo dedicado con buffer, no 1 byte.

### 7.2 ⚪ Claims de rendimiento solo de Rust y no verificables aquí

`>2M msg/s`, `<10 µs RTT`, `<50 µs streaming` (PAPER §6, RFC Apéndice C) provienen de Rust;
no hay `cargo` en este entorno para reproducirlos. Recomendación: publicar el **arnés de
benchmark** y los datos crudos (CPU, flags, payload) y enlazar un CI que los regenere, para
que sean auditables. El "<50 µs streaming" además es dudoso mientras §4.6 no se resuelva.

### 7.3 ⚪ Matizar el ahorro en los docs

La calculadora (la corrí) reproduce los números por mensaje (heartbeat 58%, stream 46%,
tools/list 37%) pero el **agregado real es 12.4%**, dominado por payloads grandes opacos
(file_context 3.6%, porque LUMEN solo comprime claves, no valores). El "40–80%" es cierto
solo para mensajes pequeños/repetitivos. La proyección "$1.4M/año" parte del 12.4% × 1000
servidores × 10M llamadas/mes × ~1 MB: legítima pero agresiva. Sugerencia: mostrar también
el agregado y el desglose por tipo de tráfico, no solo los mejores casos.

---

## 8. Paridad de features entre lenguajes

**Estado real observado:**

| Feature | Rust | TS | Python | PHP | C# |
|---------|:----:|:--:|:------:|:---:|:--:|
| Hyb128 + frame + dict + compress (L1) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Crypto (ChaCha/X25519) | ⚠️ (vuln §1.1) | ❌ (no compila/WebCrypto) | ❌ | ❌ | ❌ |
| Streaming estructurado | ❌ | ❌ | ❌ | ❌ | ❌ |
| MUX (canales) | ❌ | ❌ | ❌ | ❌ | ❌ |
| BATCH / FLOW_CTL | ✅ | ❌ | ❌ | ❌ | ❌ |
| SHM (L2) | ✅ | ⚠️ (koffi FFI) | ❌ | ❌ | ❌ |
| QUIC (L4) | ⚠️ (feature) | ❌ | ❌ | ❌ | ❌ |
| Macaroons | ❌ | ❌ | ❌ | ❌ | ❌ |

**Cómo arreglarlo:** definir un **perfil de conformidad mínimo** (L1 + framing + dict +
compress + handshake) que las 5 impls DEBEN cumplir, y marcar el resto como extensiones por
implementación en una matriz pública. Hoy el PAPER (§5) y el RFC (Apéndice C) sugieren
mayor uniformidad de la que hay.

> Nota: no audité línea a línea `shm.rs`, `datagram.rs`, `quic.rs`, `wasm.rs`, `ffi.rs`,
> `cadencia.*`, los servidores MCP (`filesystem/thinking/web`), ni `LumenCompress.cs`/
> `Dict.cs`/`LumenFFI.cs`. Merecen el mismo tratamiento; en particular revisar en `shm.rs`
> el `std::mem::forget(region)` del handshake (`:101`, `:174`) — fuga deliberada de la
> región mapeada que hay que documentar como propiedad de por vida y verificar que no
> filtra ficheros `/dev/shm` huérfanos al cerrar sesiones.

---

## 9. Documentación y repositorio

### 9.1 🟡 Falta LICENSE

El README dice "MIT — see LICENSE" con enlace, pero **no existe el fichero**. Añadir
`LICENSE` (MIT) en la raíz.

### 9.2 🟡 Claims a verificar/corregir

- README portada: `✅ 29 tools — works with Hermes` enlazando a
  `NousResearch/hermes-agent/pull/47740`. El número de PR es implausible; **verificar el
  enlace** o retirarlo de portada.
- Incoherencia: "29 tools" (README:20) vs "18 tools, 3 servers" (README:117; 9+2+7=18).
- "✅ 217/217 e2e passing" (PHP): documentar cómo se reproduce (`composer test`?) o ajustar.

### 9.3 ⚪ Ruido commiteado

Quitar del control de versiones y añadir a `.gitignore`:
`bench_stderr*.txt`, `bench.ts.bak`, `__pycache__/`, `dist/`, `*.egg-info/`,
`bench_results*.json`, `bench_out.json`, `report_python.json`, `.work_log.json`,
`tests/e2e/golden/` (si se regenera en CI).

### 9.4 ⚪ Consistencia EN/ES

Mantener PAPER/RFC/SPEC/README en EN y ES sincronizados tras los cambios (hoy hay ~10
documentos espejo; un cambio de protocolo obliga a tocar todos — considerar generar las
tablas compartidas desde una fuente única).

---

## 10. Checklist accionable (resumen)

**Bloqueantes (🔴):**
- [ ] Derivar claves send/recv con HKDF; un AEAD por sentido (Rust `crypto.rs`/`handshake.rs`, TS `crypto.ts`). Test negativo.
- [ ] Definir encoding canónico de números y arreglar `compress.ts:121`; añadir vectores float/int límite.
- [ ] Reparar `crypto.ts` (tipos + usar ChaCha real, no WebCrypto); que `npm run build && npm test` pase.
- [ ] Importar `parse_ack` en `transport.py`; test de WebSocket.

**Altos (🟠):**
- [ ] Acotar `FrameAssembler`/fragmentos/Hyb128/streams con `max_frame` (DoS).
- [ ] Ventana anti-replay en crypto.
- [ ] Reescribir RFC/PAPER: endianness LE, sin DICT_REF, `LEN`=payload, no-CBOR (o migrar), dict real de 128, payloads §5 reales o marcados como previstos, quitar boilerplate IETF.
- [ ] Regenerar `conformance.json` desde el código + CI de interop multi-lenguaje.
- [ ] Decidir macaroons: construir o degradar el claim.

**Medios/bajos (🟡/⚪):**
- [ ] Lectura por bloques en transporte Python; imports muertos; `ParseError` coherente.
- [ ] Matriz de paridad de features pública; perfil de conformidad mínimo.
- [ ] LICENSE; corregir "29 vs 18"; verificar Hermes; limpiar artefactos; sincronizar EN/ES.

---

*Documento generado tras revisión y ejecución reales (pytest 94/94, e2e 89/89,
comparación byte a byte TS↔Python 27/28, `tsc --noEmit` 6 errores). Las cifras de Rust
(rendimiento, tests cargo) no se pudieron reproducir por ausencia de toolchain en el
entorno y quedan pendientes de auditoría con `cargo test`/`cargo bench`.*
