# Plan de mejoras exhaustivo para LUMEN Protocol

Fecha de revision: 2026-06-17  
Repositorio revisado: `/Users/gporto/Desktop/projects2/lumen-protocol`  
Alcance: especificacion, RFC, documentacion publica, implementaciones Rust/Python/TypeScript/PHP/C#, FFI, transportes, servidores MCP, ejemplos, pruebas y empaquetado.

## Resumen ejecutivo

LUMEN Protocol es un proyecto ambicioso y con una intuicion fuerte: reducir el coste de JSON-RPC/MCP con un formato binario pequeno, diccionarios estaticos/de sesion y transportes optimizados. La idea tiene valor, y el repositorio ya contiene mucho trabajo: RFC, implementaciones en varios lenguajes, golden tests, demos, servidores MCP y prototipos de transportes.

El problema principal es que el proyecto aparenta estar mas estabilizado de lo que realmente esta. La documentacion habla de produccion, paquetes publicados, compatibilidad completa, QUIC, C#, PHP y ahorros concretos, pero el codigo y las pruebas muestran que todavia hay divergencias importantes entre especificacion e implementaciones. Tambien hay fallos de seguridad en la capa criptografica, parsing no estricto, DoS por limites incompletos, problemas de interoperabilidad, tests que no se ejecutan realmente y paquetes que no compilan en el entorno actual.

Mi opinion: antes de anadir funcionalidades, el proyecto necesita una fase de consolidacion. La prioridad debe ser convertir LUMEN de "prototipo prometedor multilenguaje" a "protocolo verificable con una unica fuente de verdad". Eso significa congelar wire format, corregir seguridad, hacer que CI compile todo, generar vectores canonicos y bajar las promesas publicas hasta que esten demostradas.

## Estado observado de verificaciones

Estas comprobaciones se ejecutaron localmente durante la revision:

| Area | Comando | Resultado |
| --- | --- | --- |
| Git | `git status --short` | Arbol limpio antes del informe |
| Inventario | `rg --files -uu` | Repo con docs, Rust, Python, TypeScript, PHP, C#, MCP servers, ejemplos, golden tests, binarios y caches |
| Rust | `cargo test` | No ejecutable: `cargo: command not found` |
| Python | `python3 -m pytest -q` en `implementations/python` | Falla en coleccion con Python 3.9.6 por sintaxis `A | B`; el proyecto requiere >=3.10 |
| TypeScript | `npm test` en `implementations/typescript` | Pasa con 0 tests porque `dist/**/*.test.js` no existe |
| TypeScript | `npm run build` | Falla: `tsc: command not found`; dependencias no instaladas |
| TypeScript crypto | prueba Node WebCrypto | Node v26 soporta X25519 experimentalmente, pero rechaza `ChaCha20-Poly1305` con `NotSupportedError` al importar clave raw |
| PHP | `php tests/e2e_test.php` | 181 pasados, 36 fallidos, 217 total; fallos de compatibilidad binaria de frames JSON |
| C# | `dotnet test` en `implementations/csharp` | No ejecutable: `dotnet: command not found` |
| PHP runtime | `php -v` | PHP 8.4.22 disponible |
| Python runtime | `python3 --version` | Python 3.9.6 disponible |
| Node runtime | `node -v` | Node v26.3.0 disponible |

Lectura honesta: ahora mismo no hay evidencia local de que Rust, TypeScript o C# compilen en este entorno; Python no puede correr con el Python del sistema; PHP si ejecuta, pero falla parte relevante de compatibilidad binaria.

## Prioridades

### P0 - Bloqueante

Debe resolverse antes de declarar compatibilidad, seguridad o uso en produccion.

- Una unica fuente de verdad para el wire format.
- CI que compile y pruebe cada implementacion.
- Correccion de criptografia, replay, autenticacion y QUIC inseguro.
- Parsers estrictos para evitar trailing bytes, valores no canonicos y DoS.
- Vectores golden generados desde una especificacion canonica, no desde una implementacion accidental.
- Documentacion que no afirme estados no demostrados.

### P1 - Alta

Necesario para una primera version publica fiable.

- Alinear README/RFC/SPEC_DEV/DICTIONARY con el codigo real.
- Corregir incompatibilidades entre lenguajes.
- Endurecer transportes stdio, mmap/shm, datagram, mux, stream y handshake.
- Empaquetado limpio por lenguaje.
- Tests negativos, fuzzing y property tests.

### P2 - Media

Mejora de ergonomia, rendimiento y mantenibilidad.

- APIs con errores tipados y modos strict/lenient.
- Benchmarks reproducibles con datasets versionados.
- Mejoras de zero-copy y allocaciones.
- Demos y servidores MCP separados de claims de produccion.

### P3 - Baja

Pulido y presentacion.

- Limpieza de estilo, typos, BOMs, tablas, ejemplos curl, fechas y naming.
- Dashboards/demos mas modestos y medibles.
- Mejor experiencia para contribuidores.

## Diagnostico general

### 1. El proyecto no tiene una fuente de verdad unica

Hay al menos cuatro documentos que describen el protocolo con diferencias sustanciales:

- `RFC_LUMEN.md`
- `RFC_LUMEN_ES.md`
- `SPEC_DEV.md`
- `DICTIONARY.md`

Ademas, las implementaciones Rust/Python/TypeScript/PHP/C# codifican decisiones propias. Esto crea una situacion peligrosa: un lector no puede saber si el protocolo real es lo que dice el RFC, lo que dice `SPEC_DEV`, lo que hace Rust, lo que hacen los golden tests o lo que hacen las demos.

Acciones:

- Elegir una fuente normativa unica. Recomendacion: `RFC_LUMEN.md` como documento normativo y `SPEC_DEV.md` como notas no normativas o eliminarlo/renombrarlo a `NOTES_DEV.md`.
- Crear una tabla "Normative status" al principio de cada documento:
  - Normativo: `RFC_LUMEN.md`, `DICTIONARY.md`, `tests/golden/*.json`.
  - Informativo: `README.md`, `PAPER.md`, ejemplos, retrospectivas, benchmarks.
- Bloquear cambios al wire format sin actualizar primero la fuente normativa y los vectores golden.
- Anadir una regla CI: si cambia `RFC_LUMEN.md`, deben regenerarse o validarse golden vectors.

Criterio de aceptacion:

- Un lector puede implementar LUMEN solo leyendo el RFC y los vectores golden.
- `SPEC_DEV.md` ya no contradice al RFC, o esta marcado explicitamente como historico.
- Cada implementacion tiene tests que prueban conformidad contra los mismos vectores.

### 2. El RFC mezcla identidad de estandar con disclaimer de no-IETF

`RFC_LUMEN.md` dice que es una especificacion independiente y que no es un RFC del IETF, pero conserva secciones como:

- "Status of This Memo: Internet Standards Track"
- copyright/trust wording estilo IETF
- consideraciones IANA y registros que parecen oficiales

Esto puede crear confusion legal y tecnica.

Acciones:

- Sustituir todo el boilerplate estilo IETF por una cabecera propia:
  - "LUMEN Protocol Specification"
  - "Independent Internet-Draft style document"
  - "No IETF status"
  - "Registry maintained by the LUMEN project"
- Renombrar "IANA Considerations" a "LUMEN Registry Considerations" salvo que exista un proceso IANA real.
- Si se mantiene el estilo RFC, usar "Internet-Draft style" y no "Internet Standards Track".

Criterio de aceptacion:

- No hay frases que impliquen aprobacion IETF/IANA si no existe.
- Los registros de tipos, flags, tags y transportes tienen propietario claro dentro del repo.

### 3. Fechas y estados publicos deben corregirse

El RFC contiene fecha "18 June 2026", que es futura respecto a esta revision del 17 de junio de 2026. README y apendices hablan de paquetes publicados y estados de produccion que no quedan demostrados por el repo.

Acciones:

- Corregir fecha efectiva del documento o marcarla como draft futuro.
- Anadir `Status: Draft`.
- Separar "implemented", "tested", "published", "production-ready".
- No usar "production" salvo que haya CI verde, release firmada y documentacion operativa.

Criterio de aceptacion:

- La tabla de estado refleja lo que se puede verificar con comandos.
- No hay claims de compatibilidad completa sin enlace a CI o artefacto.

## Inconsistencias especificacion vs codigo

### 4. Registro de tipos de frame inconsistente

Rust define:

- `TYPE_BATCH = 0x0D`
- `TYPE_FLOW_CTL = 0x0E`

Pero el RFC marca `0x0D-0x0E` como no asignados. Eso rompe la autoridad del registro.

Acciones:

- Decidir si batch y flow control son parte de v0.1.
- Si lo son, registrarlos en el RFC con formato exacto.
- Si no lo son, moverlos a rango experimental o feature-gated.
- Actualizar Python/TypeScript/PHP/C# para reconocerlos o rechazarlos de forma definida.

Criterio de aceptacion:

- La tabla de frame types coincide byte a byte en todas las implementaciones.

### 5. MUX tiene formatos incompatibles

`SPEC_DEV.md` describe MUX como `[CHANNEL:1B][CTRL:4b]` y 256 canales. Rust usa otro esquema con `sub_command` y `u16 channel_id`. Esto no es un detalle: cambia el wire format.

Acciones:

- Definir formato MUX definitivo:
  - ancho de channel id
  - comandos validos
  - payload permitido por comando
  - credit/flow-control
  - cierre y errores
- Actualizar RFC y borrar el formato alternativo.
- Crear vectores golden de MUX:
  - open
  - data
  - close
  - reset/error
  - command desconocido
  - payload extra prohibido

Criterio de aceptacion:

- Rust, Python, TypeScript, PHP y C# parsean/rechazan los mismos bytes.

### 6. Streaming tiene formatos incompatibles

`SPEC_DEV.md` habla de `STREAM_ID:2B`, burst length y tipos token con `u16/u32/f32 embeddings`. Rust usa `u32 stream_id`, `u32 token_seq` y `u8 token_type`. El RFC tampoco deja suficientemente cerradas todas las reglas de validacion.

Acciones:

- Elegir formato definitivo de stream:
  - `stream_id` de 32 bits o 16 bits
  - `token_seq` obligatorio o no
  - enum de token type
  - payload vacio obligatorio para `TOKEN_END`
  - rango valido de temperatura/probabilidades si aplica
- Definir ordenamiento, duplicados, reinicio, cierre y backpressure.
- Crear tests negativos para trailing bytes y token types desconocidos.

Criterio de aceptacion:

- Un stream malformado se rechaza igual en todos los lenguajes.

### 7. DICT_SYNC esta descrito de varias maneras

`SPEC_DEV.md` incluye `OP + ENTRY_COUNT`, mientras que el RFC describe `entry_count + entries` sin la misma estructura. El codigo de diccionario de sesion existe, pero no hay una historia completa y uniforme de sincronizacion.

Acciones:

- Definir si DICT_SYNC es:
  - snapshot completo
  - delta
  - operaciones add/remove/reset
  - confirmacion acked o fire-and-forget
- Definir conflicto de IDs:
  - si un ID ya existe
  - si una key ya existia con otro ID
  - si se llena el rango `0x80..0xFE`
- Anadir versionado de diccionario y epoch de sesion.
- Crear golden vectors:
  - add key
  - duplicate key
  - duplicate id
  - reset
  - overflow
  - UTF-8 invalido

Criterio de aceptacion:

- La misma secuencia DICT_SYNC produce el mismo diccionario en todos los lenguajes.

### 8. Handshake/negociacion no coincide entre documentos e implementaciones

El RFC define `TRANSPORT_INIT/ACK` con campos binarios. `SPEC_DEV.md` habla de JSON `{caps:["mmap","stdio"]}`. Rust `handshake.rs` usa JSON para PROBE/ACK en algunas rutas. Python/TypeScript usan payload comprimido para probe. Esto es uno de los puntos mas criticos de interoperabilidad.

Acciones:

- Elegir una unica negociacion para v0.1:
  - opcion A: handshake binario puro con tipos `TRANSPORT_INIT/ACK`
  - opcion B: probe LUMEN comprimido sobre frame normal
  - opcion C: JSON fallback primero y upgrade posterior
- Documentar exactamente:
  - bytes iniciales
  - timeout
  - fallback a JSON-RPC
  - que pasa si el peer escribe datos antes del ACK
  - si se permite probe sobre stdout/stdin de servidores JSON-RPC existentes
- Implementar replay buffer para datos consumidos durante probe si hay fallback.

Criterio de aceptacion:

- Un cliente LUMEN puede conectarse a:
  - servidor LUMEN
  - servidor JSON-RPC puro que ignora basura
  - servidor JSON-RPC puro que falla ante basura
  - servidor que envia datos antes de ack
- En todos los casos el comportamiento esta definido y testeado.

## Seguridad

### 9. Bug P0 en anti-replay de crypto

En Rust y TypeScript, la ventana de recepcion empieza en 0. El primer frame cifrado con nonce 0 cae en la rama de reutilizacion y puede rechazarse como `NonceReuse`. Ademas, las pruebas internas parecen esperar que el primer decrypt funcione, lo que sugiere que el test suite real detectaria esto si compilase.

Impacto:

- Canal cifrado puede fallar en el primer mensaje.
- Diferentes implementaciones pueden divergir segun inicialicen nonce.

Acciones:

- Inicializar `recv_window` como "sin nonces recibidos" usando `Option<u64>`/sentinela.
- Aceptar nonce 0 una sola vez.
- Anadir pruebas:
  - primer nonce 0 aceptado
  - replay de nonce 0 rechazado
  - nonce 1 aceptado
  - nonce antiguo fuera de ventana rechazado

Criterio de aceptacion:

- Rust y TypeScript pasan los mismos vectores anti-replay.

### 10. La ventana anti-replay se actualiza antes de autenticar

En `crypto.rs` y `crypto.ts`, el estado anti-replay puede actualizarse antes de comprobar que AEAD autentica el ciphertext. Un atacante puede enviar un nonce alto con ciphertext invalido y desplazar la ventana, causando denegacion de servicio a frames legitimos posteriores.

Acciones:

- Separar `check_nonce_candidate(nonce)` de `commit_nonce(nonce)`.
- Autenticar primero.
- Solo actualizar ventana tras decrypt correcto.
- Anadir test:
  - ciphertext invalido con nonce alto no mueve ventana
  - siguiente frame legitimo con nonce bajo dentro de ventana sigue entrando

Criterio de aceptacion:

- AEAD invalido nunca cambia estado de sesion.

### 11. AEAD no autentica metadatos de frame

El cifrado autentica el payload, pero no queda claro que autentique tipo, flags y longitud del frame. Si el header queda fuera de AAD, un atacante puede cambiar metadatos no cifrados y provocar interpretaciones distintas.

Acciones:

- Definir AAD normativo:
  - frame type
  - flags canonicos
  - payload length canonico
  - session id/transport epoch si aplica
- Implementar `seal_frame(type, flags, payload)` y `open_frame(type, flags, ciphertext)`.
- Rechazar cambios de tipo/flags si no autentican.

Criterio de aceptacion:

- Un ciphertext valido con tipo modificado falla al abrir.
- Un ciphertext valido con flags modificados falla al abrir.

### 12. Handshake X25519 no autentica identidad

X25519 da secreto compartido, pero sin autenticacion hay MITM. Ademas, `validate_public_key` en Rust apenas rechaza all-zero y contiene una comparacion que siempre parece verdadera. El handshake no parece llamar sistematicamente a validacion fuerte.

Acciones:

- Documentar el modelo de amenaza:
  - solo cifrado oportunista
  - autenticado por TLS externo
  - autenticado por firma Ed25519
  - autenticado por certificados
- Rechazar claves publicas de bajo orden y shared secrets all-zero.
- Si LUMEN quiere seguridad de canal propia, anadir transcript hash y firma de identidad.
- Si no, decir claramente: "LUMEN crypto is experimental; use TLS/stdio trust boundary".

Criterio de aceptacion:

- El RFC no promete autenticacion si no existe.
- Tests cubren claves all-zero/low-order y MITM conceptual.

### 13. Macaroons no usan HMAC real

`macaroon.rs` tiene una funcion/documentacion `hmac_sha256`, pero la implementacion usa HKDF expand y despues SHA256 del mensaje. Eso no es HMAC-SHA256.

Impacto:

- Tokens pueden dar una falsa sensacion de seguridad.
- Incompatibilidad con bibliografia/expectativas de macaroons.

Acciones:

- Usar crate `hmac` + `sha2`.
- Crear vectores de test para:
  - firma base
  - caveat first-party
  - caveat third-party si aplica
  - tamper de id/location/caveat
- Renombrar cualquier funcion interna que no sea HMAC.
- Validar version y trailing bytes en decode.

Criterio de aceptacion:

- Macaroon modificado en cualquier byte falla.
- La implementacion coincide con vectores documentados.

### 14. QUIC acepta cualquier certificado por defecto

`quic.rs` usa un `SkipCertVerifier`/verificador permisivo y lo instala como configuracion de cliente por defecto. Esto no debe existir como default de produccion.

Acciones:

- Quitar verifier inseguro del default.
- Moverlo a feature `dangerous-insecure-test-cert`.
- Exigir trust roots o pinning.
- Documentar como levantar servidor local con certificado self-signed solo para tests.

Criterio de aceptacion:

- Un cliente QUIC default rechaza certificado no confiable.
- Los tests que necesiten self-signed optan explicitamente al modo inseguro.

### 15. SSRF incompleto en servidor web MCP

`implementations/mcp-servers/web/server.py` intenta bloquear hosts privados, pero:

- valida DNS antes de `urlopen`, y `urlopen` puede resolver otra vez
- urllib sigue redirects por defecto
- faltan rangos no globales/reservados
- para HTTPS usa puerto 80 si `parsed.port` no esta presente
- lee la respuesta completa antes de truncar

Acciones:

- Bloquear todo IP que no sea global usando `ipaddress.ip_address(...).is_global`.
- Validar cada redirect antes de seguirlo.
- Evitar DNS TOCTOU conectando al IP validado con `Host` header o usando resolver controlado.
- Aplicar limite de bytes durante lectura, no despues.
- Limitar content-encoding y tamano descomprimido.
- Anadir timeout total y limite de redirects.

Criterio de aceptacion:

- Tests SSRF para localhost, RFC1918, link-local, IPv6 local, redirect a private, DNS rebinding simulado.

### 16. Servidor filesystem MCP necesita hardening operativo

`shared_tools.py` resuelve rutas dentro de `ALLOWED_ROOTS`, lo cual es buena base, pero faltan limites y protecciones:

- busquedas regex sin timeout ni limite fuerte de coste
- `rglob` puede recorrer arboles enormes
- no hay politica clara de symlinks durante traversal
- escrituras no atomicas
- `write_file` puede crear padres y sobrescribir demasiado facil
- contenido sin limite de tamano

Acciones:

- Definir limites:
  - max files
  - max bytes leidos
  - max resultados
  - timeout por busqueda
  - ignore dirs por defecto: `.git`, `node_modules`, `target`, `dist`, `.venv`
- Escritura atomica con tempfile + rename.
- Opcion `overwrite=false` por defecto para creacion.
- Auditoria de symlinks en cada file visitado.
- Tests de escape por symlink y regex costosa.

Criterio de aceptacion:

- No se puede leer/escribir fuera de roots aunque haya symlinks.
- Una busqueda patologica termina por limite.

### 17. Fallback LUMEN a JSON-RPC puede perder datos

Python/TypeScript transport consumen bytes durante negociacion. Si el servidor envia JSON-RPC antes de que termine el probe, esos bytes pueden perderse al caer a fallback. TypeScript ademas puede dejar listeners vivos tras timeout.

Acciones:

- Implementar buffer de bytes/lineas consumidas durante probe.
- Reinyectar ese buffer al parser JSON si hay fallback.
- Limpiar listeners en todos los caminos de timeout/error.
- Evitar enviar bytes binarios a servidores JSON-RPC que no declaren soporte, o hacerlo solo tras un envelope seguro.

Criterio de aceptacion:

- Test con servidor que responde inmediatamente en JSON durante ventana de probe.
- No hay mensajes perdidos ni listeners duplicados.

## Wire format y parsing

### 18. Falta modo estricto obligatorio

Varias implementaciones aceptan:

- trailing bytes tras payload comprimido
- bools no canonicos
- counts gigantes truncados
- frame flags reservados
- Hyb128 no canonico
- comandos desconocidos con payload arbitrario

Acciones:

- Definir dos modos:
  - strict: obligatorio para wire/network/CI
  - permissive: solo para herramientas de diagnostico
- Strict debe rechazar:
  - trailing bytes
  - valores no canonicos
  - flags reservados
  - lengths por encima de max_frame
  - counts por encima de max_count
  - UTF-8 invalido
  - IDs de diccionario desconocidos si no hay fallback especificado

Criterio de aceptacion:

- Todas las APIs publicas de parse/decompress usadas en transporte usan strict por defecto.

### 19. `decompress` acepta trailing bytes

Rust, Python, TypeScript, PHP y C# tienen variantes de decompress que decodifican un valor y no exigen que el cursor termine exactamente al final.

Impacto:

- Malformed payloads pueden pasar.
- Diferentes capas pueden ignorar datos inyectados.
- Se complica la firma/autenticacion del contenido.

Acciones:

- Cambiar API strict para requerir `pos == data.len()`.
- Exponer `decompress_prefix` si realmente se necesita parse incremental.
- Anadir golden negative: `null + 0x00`, object valido + basura, string valido + basura.

Criterio de aceptacion:

- Todo trailing byte produce error en strict.

### 20. Arrays/objetos gigantes se truncan silenciosamente

Python, TypeScript, PHP y C# usan patrones de `min(count, 1024)` o truncado. Eso es peor que fallar, porque acepta un mensaje distinto al enviado.

Acciones:

- Si `count > MAX_COUNT`, devolver error.
- No truncar de forma silenciosa.
- Documentar `MAX_CONTAINER_ITEMS`.
- Hacer que encode rechace mas de 1024 si ese es el limite.

Criterio de aceptacion:

- Payload con count 1025 falla en todos los lenguajes.

### 21. Bool no canonico

Rust/PHP aceptan cualquier no-cero como true en algunos decoders. El wire format debe definir si bool es solo `0x00/0x01`.

Acciones:

- Definir bool como `0` o `1`.
- Rechazar `2..255`.
- Vectores negativos.

Criterio de aceptacion:

- `bool(2)` falla.

### 22. Numeros enteros y flotantes no estan completamente definidos

Problemas observados:

- Rust puede perder precision con `serde_json::Number` u64 grande al caer a f64.
- TypeScript usa Number/bitwise para enteros que pueden exceder 32 bits.
- PHP y C# difieren con `0.0` frente a entero 0.
- Golden PHP salta casos como `float_zero`.

Acciones:

- Definir numeric model:
  - rango i64 exacto
  - soporte u64 o no
  - float64 IEEE 754
  - NaN/Infinity prohibidos
  - canonicalizacion de `0.0`
- Separar tags para signed int, unsigned int y float si hace falta.
- En TypeScript usar BigInt para i64/u64 o rechazar fuera de safe integer.
- En PHP definir cuando `0.0` se codifica como float.

Criterio de aceptacion:

- Vectores golden para `0`, `-1`, `2^31`, `2^53-1`, `2^63-1`, `u64 max` si aplica, `0.0`, `-0.0`, `1.5`.

### 23. Hyb128 no tiene reglas canonicas suficientemente aplicadas

Problemas:

- Python `hyb128.py` calcula mal el numero de bytes consumidos en extended mode por un `+1` duplicado.
- Python no valida negativos en `encoded_len`/`encode`.
- TypeScript usa bitwise y queda limitado a 32 bits pese a documentar mas.
- Rust parsea, pero el frame parser no parece imponer canonical/minimal encoding.

Acciones:

- Definir Hyb128 normativo:
  - short mode para `0..127`
  - extended mode para `128..MAX`
  - encoding minimo obligatorio
  - max bytes
  - si MAX es u64 o menor
- Implementar `decode_strict`.
- Tests property:
  - decode(encode(n)) == n
  - encoded_len(n) == len(encode(n))
  - valores no minimos rechazados

Criterio de aceptacion:

- Python corrige extended length.
- TypeScript usa BigInt o rechaza >u32 de forma declarada.

### 24. Flags reservados y flags por tipo no se validan

El parser de frames suele aceptar flags desconocidos. Ademas, `FLAG_FLOW_PAUSE = 0x01` en Rust colisiona con `FLAG_COMPRESSED = 0x01`, por lo que `is_compressed()` puede devolver true en frames flow-control.

Acciones:

- Definir flags globales y flags especificos por frame type.
- Reservar `0x01` solo para compressed si es global.
- Para flow control, mover pause/resume a payload o a flag no global con validacion por tipo.
- Rechazar flags reservados en strict.

Criterio de aceptacion:

- Flow pause no se interpreta como compressed.
- Flags desconocidos fallan en strict.

### 25. `Frame::build` puede hacer panic con buffers pequenos

Rust `build` panica si el buffer no alcanza. Para una libreria de protocolo, la API publica debe devolver error, no tumbar el proceso.

Acciones:

- Introducir `try_build(...) -> Result<usize, Error>`.
- Mantener `build_unchecked` solo interno/test si hace falta.
- Actualizar FFI para devolver error y mensaje.

Criterio de aceptacion:

- Buffer insuficiente no produce panic.

## Rust

### 26. `lib.rs` expone `quic` sin feature-gating coherente

`Cargo.toml` marca `quinn`, `tokio`, `rustls`, `rcgen` como opcionales bajo feature `quic`, pero `src/lib.rs` publica `pub mod quic;` de forma incondicional. Si `quic.rs` usa crates opcionales incondicionalmente, el build default falla.

Acciones:

- Cambiar a `#[cfg(feature = "quic")] pub mod quic;`.
- Si hay tipos publicos dependientes de QUIC, exponer stubs con error claro o reexport condicionado.
- CI debe probar:
  - `cargo test --no-default-features`
  - `cargo test --features quic`
  - `cargo test --all-features`

Criterio de aceptacion:

- Build default de Rust compila sin crates QUIC.

### 27. Dependencia `rand_core` posiblemente no declarada

`macaroon.rs` usa `rand_core::RngCore`. Si no esta como dependencia directa, puede romper compilacion o depender accidentalmente de dependencias transitivas.

Acciones:

- Declarar `rand_core` directamente o usar API de `rand`.
- CI con `cargo check` limpio.

Criterio de aceptacion:

- No hay imports desde dependencias transitivas no declaradas.

### 28. `compress.rs` necesita limites y canon

Problemas:

- trailing bytes aceptados
- bool no canonico
- recursion sin limite claro
- counts pueden causar loops grandes
- u64 grande puede perder precision al convertirse a f64

Acciones:

- `DecodeOptions { max_depth, max_items, strict }`.
- Rechazar count excesivo antes de reservar/iterar.
- Soportar u64 explicitamente o rechazarlo.
- Tests negativos por cada tag.

Criterio de aceptacion:

- Fuzzer de `decompress` no encuentra panics ni OOMs con limites pequenos.

### 29. `dict.rs` deja mappings stale al registrar key repetida

`SessionDict::register(key, id)` no elimina correctamente mappings antiguos si la misma key cambia de id. Puede quedar un ID viejo apuntando a una key que ya no deberia estar ahi.

Acciones:

- Al registrar:
  - si key existia con old_id, limpiar forward[old_id]
  - si id existia con old_key, limpiar reverse[old_key]
  - insertar nueva relacion
- Tests de key duplicada, id duplicado y eviction.

Criterio de aceptacion:

- Nunca hay dos IDs activos para una misma key.

### 30. `evict_lru` documenta una cosa y hace otra

La doc dice que devuelve `None` si hay slot vacio, pero la implementacion puede devolver `Some(empty_id)`. Eso confunde al caller.

Acciones:

- Alinear doc e implementacion.
- Ideal: separar `first_free_slot()` de `evict_lru()`.

Criterio de aceptacion:

- Tests cubren diccionario parcialmente lleno y lleno.

### 31. `handshake.rs` fuga mmap/shared memory

Uso de `mem::forget(region)` para evitar drop implica fuga deliberada y posible falta de unlink/cleanup. Un transporte debe poseer la region mientras viva y liberarla al cerrar.

Acciones:

- Guardar `ShmRegion` en una estructura de transporte.
- Usar `Arc<ShmRegion>` si se comparte.
- Implementar `Drop`/cleanup claro.

Criterio de aceptacion:

- Test crea/cierra handshake SHM y no deja recursos persistentes.

### 32. `handshake.rs` marca payload JSON como compressed

Algunas rutas construyen frames con `FLAG_COMPRESSED` aunque el payload es `serde_json::to_vec`, no LUMEN compressed. Un receptor que respete el flag intentara descomprimir JSON crudo.

Acciones:

- Si `FLAG_COMPRESSED`, usar `compress_value`.
- Si es JSON crudo, no marcar compressed y documentar content type.
- Vectores de PROBE/ACK.

Criterio de aceptacion:

- Python/TypeScript/Rust se entienden en probe/ack.

### 33. `read_frame` puede reservar memoria enorme

El handshake lee longitud y puede castear a `usize` antes de aplicar limite fuerte.

Acciones:

- Aplicar `max_frame` inmediatamente tras parsear Hyb128.
- Rechazar valores que no quepan en `usize`.
- No reservar hasta validar.

Criterio de aceptacion:

- Frame con length enorme falla sin asignacion proporcional.

### 34. `datagram.rs` trunca silenciosamente frames

`send_frame_to` y `send_frame` cortan a `MAX_DATAGRAM_SIZE`. Eso corrompe el protocolo.

Acciones:

- Devolver error `DatagramTooLarge`.
- Si se quiere soportar, implementar fragmentacion/reensamblado con IDs y checks.
- Tests de payload justo en limite y uno por encima.

Criterio de aceptacion:

- Ningun datagrama se envia truncado sin error.

### 35. `stream.rs` acepta trailing bytes y valida poco

Acciones:

- Rechazar trailing bytes.
- Validar token types.
- Exigir payload vacio para `TOKEN_END`.
- Auto-cerrar stream o proporcionar API `accept_and_close`.

Criterio de aceptacion:

- Stream malformado no queda en estado medio abierto.

### 36. `mux.rs` acepta comandos desconocidos o payload extra

Acciones:

- Enum cerrado de comandos.
- Rechazar payload extra en control frames si no esta permitido.
- Definir credit/flow-control.
- Evitar clones de inner frames en hot path.

Criterio de aceptacion:

- Tests negativos de cada comando.

### 37. `shm.rs` lee parcialmente longitud y puede desincronizar

`read_frame` hace una lectura de 4 bytes con `read(&mut lb)`. Si llega una lectura parcial, se pueden consumir bytes y perder sincronizacion.

Acciones:

- Usar `read_exact` para cabecera.
- Gestionar EOF limpio.
- Verificar `data.len() <= u32::MAX` al escribir.
- Rechazar `ShmRegion::create_impl(size < header_size)`.
- Timeout configurable para spin-wait.

Criterio de aceptacion:

- Tests con lector parcial no corrompen stream.

### 38. FFI Rust tiene contrato de errores confuso

La cabecera dice que el puntero de error dura hasta la siguiente llamada en el mismo hilo, pero la implementacion usa un `Mutex` global. `lumen_error_message` puede consumir un error global de otro hilo.

Acciones:

- Usar thread-local para last error.
- O documentar global y proteger en API.
- `lumen_shm_read_frame` no deberia perder el frame si el buffer de usuario es pequeno; debe permitir consultar tamano requerido.

Criterio de aceptacion:

- Tests multihilo de FFI error no cruzan mensajes.

## Python

### 39. El proyecto requiere Python >=3.10 pero el entorno tiene 3.9

La sintaxis `ParseComplete | ParseIncompleteHeader | ...` rompe con Python 3.9. Esto esta bien si se exige 3.10, pero README y scripts deben guiar al usuario.

Acciones:

- Documentar claramente `python >= 3.10`.
- Anadir `.python-version` o instrucciones uv/pyenv.
- CI debe correr Python 3.10, 3.11, 3.12, 3.13 si se soportan.

Criterio de aceptacion:

- `python3.10 -m pytest` verde en CI.

### 40. `hyb128.py` tiene offset incorrecto en extended mode

`_leb128_decode` devuelve `i - offset + 1` "por mode byte" y `decode_hyb128` vuelve a sumar `1 + leb_bytes`, generando longitud consumida incorrecta.

Acciones:

- `_leb128_decode` debe devolver bytes consumidos por LEB128 solamente.
- `decode_hyb128` debe sumar exactamente 1 por mode byte.
- Tests para valores 127, 128, 129, 16384.

Criterio de aceptacion:

- `decode_hyb128(encode(n)).header_len == len(encode(n))`.

### 41. Python `compress.py` confunde null valido con error

`decompress_value` devuelve solo el valor. Como `None` representa JSON null y tambien se usa para errores internos, el caller no puede distinguir malformed de null.

Acciones:

- Devolver `Result`/excepcion para errores.
- Reservar `None` como valor valido.
- `decompress_value_strict(data) -> Any` que lanza `LumenDecodeError`.

Criterio de aceptacion:

- Payload `TAG_NULL` devuelve `None`.
- Payload truncado lanza error.

### 42. Python usa diccionario de sesion global

`dict.py` mantiene singleton global. Eso rompe aislamiento entre conexiones, tests y agentes.

Acciones:

- Introducir `SessionDict` explicito.
- `compress_value(value, session=None)`.
- `Transport` debe tener su propia sesion.
- Mantener global solo para demos legacy.

Criterio de aceptacion:

- Dos conexiones con diccionarios distintos no se contaminan.

### 43. Python transport puede perder stdout durante negociacion

Acciones:

- Bufferizar bytes leidos durante `_wait_for_ack`.
- Reinyectarlos al modo JSON si fallback.
- No crear `readline` y listeners en orden que pierda lineas tempranas.
- `queue.put_nowait` dentro de `call_soon_threadsafe` debe capturar `QueueFull`.

Criterio de aceptacion:

- Test con servidor que emite JSON antes de ACK.

### 44. Python WebSocket usa siempre `TYPE_REQUEST`

La ruta WebSocket envia frames LUMEN como `TYPE_REQUEST` aunque el mensaje pueda ser response/notify.

Acciones:

- Inferir tipo desde JSON-RPC:
  - method + id -> request
  - method sin id -> notify
  - result/error -> response
- Tests de los tres.

Criterio de aceptacion:

- Tipo de frame coincide con semantica JSON-RPC.

## TypeScript

### 45. `npm test` no prueba nada sin build

El script actual ejecuta tests en `dist/**/*.test.js`. Si `dist` no existe, Node reporta 0 tests y exit code OK.

Acciones:

- Cambiar scripts:
  - `pretest: npm run build`
  - `test: node --test dist/**/*.test.js && node scripts/assert-nonzero-tests.js`
- O ejecutar tests TypeScript directamente con `tsx`.
- CI debe fallar si test count es 0.

Criterio de aceptacion:

- Un repo sin `dist` no puede pasar tests.

### 46. Build TypeScript falla sin dependencias

`npm run build` falla porque `tsc` no esta disponible.

Acciones:

- Asegurar que `typescript` esta en devDependencies.
- Documentar `npm ci`.
- CI desde checkout limpio.

Criterio de aceptacion:

- `npm ci && npm run build && npm test` verde.

### 47. WebCrypto ChaCha20-Poly1305 no es portable

En Node v26.3.0 local, `crypto.subtle.importKey('raw', ..., {name:'ChaCha20-Poly1305'})` falla con `NotSupportedError`. X25519 existe pero con warning experimental.

Acciones:

- Elegir backend crypto portable:
  - `@noble/ciphers`/`@noble/curves`
  - WebCrypto AES-GCM como perfil alternativo
  - Node `crypto` si hay soporte estable
- Detectar soporte en runtime y fallar con error claro.
- No prometer crypto TS production hasta que sea portable.

Criterio de aceptacion:

- Tests crypto TS verdes en Node LTS actual y browser objetivo.

### 48. TypeScript Hyb128/LEB128 esta limitado por bitwise 32-bit

`>>>`, `&`, `|` convierten a 32 bits. La implementacion no puede representar todo el rango si el protocolo habla de u64.

Acciones:

- Migrar a BigInt para extended.
- O declarar max `u32` y rechazar valores mayores.
- Tests con `2^32`, `2^53-1` y max permitido.

Criterio de aceptacion:

- No hay truncado silencioso.

### 49. TypeScript compression calcula strings por UTF-16

Usa `.length` para tamano de string, que cuenta code units UTF-16, no bytes UTF-8. Esto afecta size estimation y posible buffer allocation.

Acciones:

- Usar `TextEncoder.encode(str).length`.
- Reutilizar `TextEncoder/TextDecoder`.
- Tests con `n con tilde`, emoji y caracteres multibyte.

Criterio de aceptacion:

- `build_size`/compressed size coincide con bytes reales.

### 50. `index.ts` exporta FFI desde entrypoint principal

El entrypoint exporta `compress_ffi.js` y `shm_ffi.js`, que cargan `koffi`/nativo. Un usuario que solo quiera compresion JS pura puede acabar cargando dependencias nativas.

Acciones:

- Quitar FFI del entrypoint principal.
- Crear subpath exports:
  - `lumen-protocol`
  - `lumen-protocol/ffi`
  - `lumen-protocol/shm`
- Hacer imports nativos lazy.

Criterio de aceptacion:

- `import { compressValue } from "lumen-protocol"` no requiere `koffi`.

### 51. FrameAssembler TypeScript puede preasignar memoria enorme

El assembler prealloca segun length anunciado sin max_frame fuerte.

Acciones:

- `FrameAssembler({ maxFrameBytes })`.
- Rechazar length anunciado mayor al limite antes de allocation.
- No silenciar parse errors.

Criterio de aceptacion:

- Header con length gigante falla sin allocation gigante.

## PHP

### 52. Tests PHP fallan compatibilidad binaria

`php tests/e2e_test.php` da 181 pasados y 36 fallidos. Los fallos observados estan en "Frame Binary Compatibility" para payloads JSON `json_small` y `json_mcp`: PHP genera JSON con espacios, golden espera JSON compacto.

Acciones:

- Usar `json_encode(..., JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE)` y separadores compactos equivalentes si aplica.
- Definir que golden de frame raw usa bytes exactos; no "JSON semantic equivalent".
- Actualizar tests para comparar payload exacto.

Criterio de aceptacion:

- PHP golden frame compatibility: 0 fallos.

### 53. PHP decompression silencia errores

`decodeKey` devuelve string vacia en malformed/unknown, `decodeZigzag` puede devolver `[0,pos]` en malformed, arrays/objects truncados.

Acciones:

- Introducir excepciones `LumenDecodeException`.
- No usar string vacia como error.
- Rechazar unknown session key en strict.
- No truncar counts.

Criterio de aceptacion:

- Null valido y error malformado se distinguen.

### 54. PHP FrameAssembler puede ser O(n^2) y no limita buffer

Uso repetido de `substr` sobre buffer acumulado puede degradar. Falta max buffer/frame.

Acciones:

- Mantener offset de lectura en vez de cortar siempre.
- Compactar buffer solo cuando offset supere umbral.
- Anadir `maxFrameBytes` y `maxBufferedBytes`.

Criterio de aceptacion:

- Test con 10k frames pequenos no escala cuadraticamente.

### 55. PHP diccionario de sesion global

Mismo problema que Python/TypeScript/C#: estado global compartido entre conexiones.

Acciones:

- `SessionDict` por conexion.
- API legacy global marcada deprecated.

Criterio de aceptacion:

- Dos sesiones PHP no comparten keys aprendidas.

## C#

### 56. Proyecto C# es ejecutable, no libreria

`LumenCSharp.csproj` usa `OutputType Exe` y `TargetFramework net9.0`. README habla de paquete/implementacion, pero el repo contiene demo/benchmark y un `lumen.dll` nativo Windows.

Acciones:

- Separar:
  - `Lumen.Protocol` class library
  - `Lumen.Protocol.Tests`
  - `Lumen.Protocol.Benchmarks`
  - `Lumen.Protocol.Native` si aplica
- Target frameworks realistas:
  - `net8.0`
  - `net9.0` opcional
- Preparar metadata NuGet solo cuando tests esten verdes.

Criterio de aceptacion:

- `dotnet test` en CI verde.

### 57. `lumen.dll` no deberia estar trackeado asi

Hay un `implementations/csharp/lumen.dll` PE32+ Windows DLL de 1.5 MB. En macOS/Linux no sirve, y como artefacto binario dentro del repo confunde fuente con release.

Acciones:

- Mover a release artifacts o eliminar del repo.
- Si se necesita para tests Windows, descargarlo/generarlo en CI.
- Anadir `.gitignore` para binarios generados.

Criterio de aceptacion:

- Checkout fuente no contiene DLLs generadas salvo decision documentada.

### 58. C# compression puede generar payload inconsistente con objetos grandes

En encode de objeto, se escribe el count completo pero se codifican solo hasta `MAX_COUNT=1024` entradas. Eso produce payload malformed o semanticamente falso.

Acciones:

- Rechazar objetos con mas de max antes de escribir count.
- O escribir exactamente el count codificado.
- Tests de 1024 y 1025 propiedades.

Criterio de aceptacion:

- No hay truncado silencioso.

### 59. C# FFI necesita resolver nativo de forma portable

`DllImport` por nombre simple no define resolucion por OS/arch. Tambien faltan errores nativos ricos y hay casts de `nuint` a `int`.

Acciones:

- `NativeLibrary.SetDllImportResolver`.
- Mapear:
  - Windows `.dll`
  - macOS `.dylib`
  - Linux `.so`
- Exponer `lumen_error_message`.
- Validar longitud antes de convertir a array managed.

Criterio de aceptacion:

- Tests FFI pasan en al menos un OS soportado y fallan claro si lib no existe.

## Empaquetado y repo hygiene

### 60. El repo contiene caches/artefactos generados

Se observaron `__pycache__`, binarios y artefactos generados. Esto contamina revision, paquetes y diffs.

Acciones:

- Revisar `.gitignore`:
  - `__pycache__/`
  - `*.pyc`
  - `target/`
  - `dist/`
  - `node_modules/`
  - `bin/`
  - `obj/`
  - `*.dll`, `*.so`, `*.dylib` salvo excepciones documentadas
- Eliminar artefactos ya trackeados si no son fuente.

Criterio de aceptacion:

- `git clean -ndX` muestra solo ignorables esperados.

### 61. README apunta a rutas incorrectas o estados no verificados

Ejemplos:

- README menciona C# en `implementations/dotnet/`, pero existe `implementations/csharp/`.
- Estados de transporte y compatibilidad no coinciden con codigo.
- Claims de paquetes publicados no se verificaron localmente.

Acciones:

- Actualizar rutas.
- Separar "planned", "experimental", "alpha", "stable".
- Anadir comandos reales para reproducir tests por lenguaje.

Criterio de aceptacion:

- Un usuario nuevo puede seguir README desde checkout limpio.

### 62. BOM/Unicode accidental en scripts/docs

Se observaron ficheros con BOM al inicio (`DICTIONARY.md`, ejemplos Python). No es grave, pero puede molestar tooling.

Acciones:

- Normalizar a UTF-8 sin BOM.
- CI lint de encoding.

Criterio de aceptacion:

- `file`/script de comprobacion no detecta BOM salvo excepciones.

## Testing y CI

### 63. Crear matriz CI obligatoria

Propuesta GitHub Actions:

- Rust:
  - `cargo fmt --check`
  - `cargo clippy --all-targets --all-features -D warnings`
  - `cargo test --no-default-features`
  - `cargo test --all-features`
- Python:
  - `ruff check`
  - `mypy` si se decide
  - `pytest`
  - Python 3.10, 3.11, 3.12
- TypeScript:
  - `npm ci`
  - `npm run build`
  - `npm test`
  - test count > 0
- PHP:
  - `composer install`
  - `php tests/e2e_test.php`
  - `phpunit` si se migra
- C#:
  - `dotnet restore`
  - `dotnet test`
- Cross-language:
  - golden vectors
  - negative vectors
  - roundtrip matrix

Criterio de aceptacion:

- Ninguna PR puede cambiar wire behavior sin fallar/pasar golden tests.

### 64. Golden vectors deben generarse de forma reproducible

Ahora parecen existir golden tests, pero hay divergencias y skips. Hace falta un generador canonico.

Acciones:

- Crear `tests/golden/schema.json`.
- Crear `tools/generate-golden` en Rust o Python strict, pero tratado como generador normativo.
- Golden sets:
  - hyb128
  - frame headers
  - compression values
  - dictionaries
  - session dict sync
  - crypto test vectors
  - mux
  - stream
  - datagram
  - error cases
- Cada implementacion solo consume golden, no los redefine.

Criterio de aceptacion:

- Cambiar un byte de golden rompe todas las implementaciones afectadas.

### 65. Fuzzing y property tests

Acciones:

- Rust:
  - `cargo fuzz` para frame, hyb128, decompress, dict sync
  - proptest para roundtrip
- Python:
  - Hypothesis para roundtrip y malformed
- TypeScript:
  - fast-check
- PHP:
  - property tests simples o fixtures generados
- C#:
  - FsCheck o tests parametrizados

Criterio de aceptacion:

- Parsers no panican ni asignan memoria descontrolada ante bytes aleatorios.

### 66. Tests de seguridad especificos

Acciones:

- Replay:
  - nonce 0
  - replay exacto
  - nonce alto invalido
  - fuera de ventana
- AEAD AAD:
  - tipo modificado
  - flag modificado
  - length modificado
- QUIC:
  - certificado invalido rechazado
- SSRF:
  - redirect a localhost
  - DNS privado
  - IPv6 local
- Filesystem:
  - symlink escape
  - regex costosa
  - write outside root

Criterio de aceptacion:

- Tests viven en CI y no dependen de red externa.

## Benchmarks y claims de rendimiento

### 67. Los porcentajes de ahorro necesitan trazabilidad

Docs y demos hablan de 60-80% o mas. Puede ser cierto en payloads repetitivos, pero debe demostrarse con datasets y scripts reproducibles.

Acciones:

- Crear `benchmarks/` con:
  - datasets MCP reales anonimizados o sinteticos versionados
  - runner por lenguaje
  - salida JSON
  - hardware/runtime metadata
- Publicar:
  - bytes JSON compacto
  - bytes LUMEN cold
  - bytes LUMEN warm
  - CPU encode/decode
  - allocaciones
  - latencia p50/p95/p99
- README debe citar resultados generados, no numeros sueltos.

Criterio de aceptacion:

- `make bench` genera tablas que coinciden con docs.

### 68. Medir cold vs warm dictionary separadamente

El valor de LUMEN depende mucho del diccionario de sesion. Mezclar cold/warm puede inflar claims.

Acciones:

- Reportar siempre:
  - no compression/raw frame
  - static dict only
  - session dict cold
  - session dict warm after N messages
- Mostrar punto de amortizacion de DICT_SYNC.

Criterio de aceptacion:

- Benchmarks explican cuando LUMEN pierde frente a JSON compacto.

## Servidores MCP y demos

### 69. `filesystem/server.py` documenta comando incorrecto

README/docstring sugiere `node server.py`, pero es Python.

Acciones:

- Corregir a `python server.py`.
- Anadir smoke test.

Criterio de aceptacion:

- Comandos de README arrancan realmente.

### 70. `filesystem/server_native.py` parece tener bugs de frame building

Observaciones:

- `read_lumen_frame` lee byte a byte.
- Comprueba `hasattr(result, 'needed')`, pero los parse results Python usan otros campos.
- `send_lumen_frame` llama `build_size(payload)` como si el primer argumento fuese payload, pero la firma parece ser `build_size(frame_type=0, payload_len=0)`.

Acciones:

- Corregir firmas.
- Usar assembler comun.
- Crear test roundtrip native server con cliente LUMEN.

Criterio de aceptacion:

- Servidor native puede responder `tools/list` en LUMEN sin excepciones.

### 71. `thinking/server.py` mezcla herramienta util con estado volatil y salida pesada

El servidor de thinking es interesante, pero:

- guarda estado solo en memoria excepto algunas herramientas de work log si luego se implementan con persistencia
- poda cadenas viejas por numero, no por usuario/sesion
- usa emojis/Unicode en respuestas de protocolo, que esta bien para UX pero no ideal para golden/protocolo
- test suite tiene paths absolutos de Windows
- clustering TF-IDF es O(n^2) y puede crecer

Acciones:

- Separar demo de servidor mantenido.
- Hacer persistencia opcional con ruta configurada.
- Namespacing por cliente/sesion.
- Limites de longitud por thought y numero de cadenas.
- Test suite portable sin paths absolutos.

Criterio de aceptacion:

- `python test_suite.py` corre desde checkout en cualquier OS soportado.

### 72. `web/server.py` debe bajar de demo a sandbox seguro

Ademas de SSRF:

- cache key `extract:{url}` ignora `max_chars`
- lee respuesta completa antes de truncar
- HTML extraction por regex es fragil
- no hay robots/rate limits
- devuelve JSON pretty dentro de texto en vez de contenido estructurado

Acciones:

- Incluir parametros relevantes en cache key.
- Streaming read con limite.
- Parser HTML dedicado si se acepta dependencia, o documentar limitacion.
- Rate-limit por host.
- Structured MCP content.

Criterio de aceptacion:

- `max_chars` no contamina respuestas futuras con otros tamanos.

### 73. `mcp-dropin` demo permite CORS `*`

Para demo local esta bien, pero si se presenta como production-style hay que aclararlo.

Acciones:

- Cambiar copy: "demo server", no "production-style".
- CORS configurable.
- Limite de `Content-Length`.
- Responder 413 a cuerpos grandes.

Criterio de aceptacion:

- No se presenta como servidor production-ready sin hardening.

### 74. Ejemplos de agent loop y cost calculator deben declarar supuestos

Los ejemplos generan trafico sintetico y usan diccionario de sesion global. Son buenos para explicar, pero no deben usarse como prueba de ahorro real sin contexto.

Acciones:

- Incluir bloque "Assumptions".
- Mostrar semilla aleatoria, dataset y modo cold/warm.
- Exportar CSV/JSON con metadata.
- Normalizar UTF-8 sin BOM.

Criterio de aceptacion:

- Un lector no confunde simulacion con medicion de produccion.

## Documentacion

### 75. README necesita una tabla honesta de madurez

Propuesta:

| Componente | Estado sugerido ahora | Antes de marcar estable |
| --- | --- | --- |
| Wire core | Draft | RFC + golden + CI multilenguaje |
| Rust | Experimental/alpha | cargo test all-features verde |
| Python | Experimental | pytest verde en 3.10+ |
| TypeScript | Experimental | build + tests reales + crypto portable |
| PHP | Alpha | golden compatibility 100% |
| C# | Prototype | libreria + dotnet test |
| QUIC | Experimental unsafe | cert validation + feature gate |
| Crypto | Experimental unsafe | replay/AAD/auth fixes |
| MCP servers | Demo | sandbox/rate-limit/tests |

Acciones:

- Sustituir badges/claims por esta tabla.
- Enlazar a CI.
- Marcar "not production ready" hasta cerrar P0.

Criterio de aceptacion:

- La documentacion ya no vende como estable lo que no esta testado.

### 76. RFC debe incluir una seccion de compatibilidad versionada

Acciones:

- Definir version wire:
  - major/minor
  - negotiation
  - extensiones
  - comportamiento ante tipos desconocidos
- Registrar v0.1 como draft.
- Establecer que cualquier cambio incompatible sube major.

Criterio de aceptacion:

- Implementaciones pueden rechazar versiones incompatibles con error claro.

### 77. Glosario y nomenclatura

Hay terminos usados de forma intercambiable:

- frame
- payload
- compressed JSON-RPC
- native binary
- transport level
- L1/L2/L3/L4
- probe/init/ack

Acciones:

- Crear glosario normativo.
- No usar "native binary" para formatos futuros si v0.1 realmente transporta JSON-RPC comprimido.
- Mantener L1/L2/L3/L4 en todos los docs con la misma definicion.

Criterio de aceptacion:

- Cada termino tiene una definicion unica.

## Roadmap recomendado

### Fase 0 - Verdad y build basico

Objetivo: que el repo deje de contradecirse y que CI diga la verdad.

Tareas:

- Marcar todo como Draft/Experimental.
- Corregir README rutas y estados.
- Feature-gate QUIC en Rust.
- Arreglar `npm test` para no pasar con 0 tests.
- Arreglar PHP JSON compact golden failure.
- Quitar o justificar `lumen.dll`.
- CI minimo por lenguaje.
- Crear `CONFORMANCE.md`.

Aceptacion:

- CI corre y falla/pasa de forma significativa.
- No hay claims de produccion sin respaldo.

### Fase 1 - Wire format canonico

Objetivo: que todos los lenguajes hablen el mismo LUMEN.

Tareas:

- Congelar RFC v0.1.
- Alinear MUX, Stream, DICT_SYNC, Transport negotiation.
- Definir strict parsing.
- Crear golden/negative vectors.
- Corregir Hyb128 en Python/TypeScript.
- Corregir trailing bytes en todos.
- Corregir counts truncados.

Aceptacion:

- Matriz cross-language 100% verde para core wire.

### Fase 2 - Seguridad

Objetivo: que no haya fallos criptograficos obvios ni sandbox holes conocidas.

Tareas:

- Corregir replay nonce 0.
- No actualizar replay antes de AEAD.
- AAD de header.
- QUIC cert validation.
- Macaroon HMAC real.
- SSRF redirects/private ranges.
- Filesystem hardening.

Aceptacion:

- Security tests verdes.
- Crypto docs ya no sobreprometen.

### Fase 3 - Transportes maduros

Objetivo: stdio, WebSocket, SHM, datagram, QUIC y mux con limites claros.

Tareas:

- Negociacion unica.
- Fallback sin perdida de bytes.
- Datagram no truncado.
- SHM lifecycle sin fugas.
- MUX con flow-control.
- Stream con cierre y validacion.

Aceptacion:

- E2E por transporte con servidor de prueba.

### Fase 4 - Paquetes y releases

Objetivo: publicar solo lo que este probado.

Tareas:

- Rust crate con features claras.
- Python wheel/sdist.
- NPM sin FFI obligatorio.
- Composer package.
- NuGet real si C# madura.
- Release artifacts por OS para nativo.

Aceptacion:

- Instalacion desde paquete limpio y smoke test verde.

### Fase 5 - Benchmarks y adopcion

Objetivo: demostrar valor con datos reproducibles.

Tareas:

- Benchmarks reproducibles.
- Comparativas cold/warm.
- Datasets MCP versionados.
- Docs de integracion real.

Aceptacion:

- README puede afirmar ahorros con enlace a comandos y resultados.

## Lista corta de cambios inmediatos recomendados

Si quisiera maximizar impacto en pocos commits, haria esto primero:

1. Cambiar README/RFC a estado Draft/Experimental y corregir rutas/claims.
2. Feature-gate `quic` en Rust.
3. Corregir `npm test` para que falle con 0 tests.
4. Corregir PHP JSON compacto para que golden frame compatibility pase.
5. Corregir trailing bytes en decompress de todos los lenguajes.
6. Corregir anti-replay nonce 0 y update-before-auth.
7. Quitar `SkipCertVerifier` del default QUIC.
8. Corregir Hyb128 Python extended length.
9. Crear `tests/golden/negative`.
10. Abrir `CONFORMANCE.md` con matriz real de soporte.

## Conclusiones

LUMEN tiene una base interesante, pero ahora mismo el riesgo no esta en que falten ideas; esta en que hay demasiadas ideas aterrizadas de forma distinta en demasiados sitios. El proyecto necesita menos superficie nueva y mas convergencia.

La linea de trabajo mas sana es:

- primero verdad documental,
- luego wire format canonico,
- despues seguridad,
- despues transportes,
- y solo entonces paquetes/benchmarks/marketing tecnico.

Cuando esa base este cerrada, el proyecto puede quedar muy bien: un protocolo compacto para MCP/JSON-RPC con implementaciones multiples y una historia de rendimiento demostrable. Pero para llegar ahi hay que tratar la compatibilidad binaria y la seguridad como contrato, no como demo.
