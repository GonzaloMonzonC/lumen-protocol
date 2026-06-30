# Informe de vulnerabilidades — `lumen-protocol`

> Auditoría basada en lectura directa del código fuente del repositorio [GonzaloMonzonC/lumen-protocol](https://github.com/GonzaloMonzonC/lumen-protocol) (no solo documentación).
>
> Proyecto multi-lenguaje (Rust, Python, TypeScript, PHP, C#) que implementa un protocolo binario para MCP, con cifrado X25519/ChaCha20-Poly1305 y autorización mediante Macaroons.

---

## Resumen de severidad

| # | Vulnerabilidad | Componente | Tipo |
|---|---|---|---|
| 1 | Claves X25519 del peer sin validar | Rust core (`handshake.rs`) | Bypass criptográfico |
| 2 | Caducidad de Macaroon nunca comprobada | Rust core (`macaroon.rs`) | Bypass de autorización |
| 3 | Sin límite de profundidad en decompress | Rust / Python / PHP | DoS (stack overflow) |
| 4 | Servidores MCP sin cifrado/auth real | Python (`filesystem` server) | Ausencia de arquitectura de seguridad |
| 5 | TOCTOU vía symlink en `write_file` | Python (`filesystem` server) | Path traversal |
| 6 | ReDoS sin timeout en búsquedas | Python (`filesystem` server) | DoS |
| 7 | Sin límite de tamaño en SHM / TypeScript | Rust SHM / TypeScript | DoS (memoria) |
| 8 | Versión de Macaroon no validada | Rust core (`macaroon.rs`) | Integridad de protocolo |
| 9 | Memory leak intencional en negociación SHM | Rust core (`handshake.rs`) | Agotamiento de recursos |
| 10 | Sin mitigación de MITM por defecto | Todo el protocolo | Debilidad de diseño (documentada) |

---

## 🔴 Críticas

### 1. Claves públicas X25519 del peer nunca se validan en el handshake real

`crypto.rs` define `Keypair::validate_public_key()` para rechazar puntos de bajo orden (clave todo-ceros, ataques de subgrupo pequeño), y existe un test unitario que lo confirma (`low_order_point_rejected`).

Sin embargo, en `handshake.rs` —tanto en `client_encrypted_handshake` como en `server_encrypted_handshake`— la clave pública recibida del peer se decodifica de base64 y se usa directamente:

```rust
let peer_public = x25519_dalek::PublicKey::from(pk_bytes);
let shared_secret = kp.derive_shared_secret(&peer_public);
```

… **sin pasar nunca por `validate_public_key()`**. Confirmado por búsqueda global: la función solo aparece en su definición y en su propio test, nunca en código de producción.

**Impacto:** un atacante puede enviar una clave pública degenerada y forzar un secreto compartido predecible, comprometiendo la confidencialidad que el cifrado dice ofrecer.

---

### 2. El caveat de expiración de los Macaroons no se verifica nunca contra el tiempo real

`macaroon.rs` expone `caveats::expiry_before()` / `parse_expiry()` como mecanismo "canónico" de tokens con caducidad. En todo el repositorio **no existe ni una sola comparación contra la hora actual**.

Peor aún: el propio test que documenta el patrón de uso recomendado acepta el caveat sin comprobarlo:

```rust
assert!(decoded.verify(&root_key, |c| {
    caveats::parse_method(c).map_or(true, |m| m == "tools/call")
        && caveats::parse_tool(c).map_or(true, |t| t == "search")
        && caveats::parse_expiry(c).map_or(true, |_| true)   // ← siempre true
}));
```

**Impacto:** cualquier sistema de autorización construido siguiendo esta documentación tendrá macaroons que nunca expiran, sin importar la fecha que contengan.

---

### 3. Falta límite de profundidad de anidación en el decodificador de compresión — replicado en Rust, Python y PHP

`compress.rs`, `compress.py` y `Compress.php` limitan el número de elementos por array/objeto (`MAX_COUNT = 1024`), pero **ninguno limita la profundidad de anidación**. La función de decodificación de valores se llama recursivamente sin contador de profundidad en las tres implementaciones.

Un payload de pocos cientos de bytes (`[[[[[...]]]]]` anidado miles de veces) provoca recursión sin freno:

- En **Python**: `RecursionError` no controlado.
- En **Rust**: sin red de seguridad — **stack overflow real que aborta el proceso**.
- En **PHP**: mismo patrón (`MAX_COUNT` presente, sin control de profundidad).

**Impacto:** DoS trivial de explotar contra cualquier servidor que acepte frames LUMEN no confiables. Al estar duplicado en tres implementaciones independientes, es un fallo de la especificación del protocolo, no un descuido aislado.

---

### 4. Los servidores MCP de producción no aplican ninguna de las protecciones criptográficas/de autorización del protocolo

`server.py` y `server_native.py` —el servidor `filesystem`, el que se distribuye para uso con Hermes Agent— no usan cifrado, ni Macaroons, ni ningún control de acceso. Es JSON-RPC (o el binario LUMEN) plano sobre stdio.

Todo el aparato de seguridad documentado (X25519, ChaCha20-Poly1305, Macaroons) vive aislado en la librería *core* sin conectarse al software que realmente procesa peticiones de lectura/escritura de archivos.

**Impacto:** el README anuncia *"Zero-trust Macaroons"* y *"Wire encryption"* como features del protocolo, pero **ningún MCP server real del repositorio las usa**. Un usuario que instale el servidor `filesystem` confiando en esas garantías no está protegido por ellas.

---

## 🟠 Altas

### 5. Sandboxing de filesystem vulnerable a TOCTOU vía symlinks

`shared_tools.py::resolve_path()` resuelve symlinks y comprueba pertenencia a `_ALLOWED_ROOTS` en el momento de la llamada:

```python
resolved = resolved.resolve()
if not any(resolved.is_relative_to(root) for root in allowed):
    raise PermissionError(f"Path escapes allowed roots: {resolved}")
```

Pero `tool_write_file` ejecuta `path.parent.mkdir(parents=True, exist_ok=True)` y luego escribe un archivo temporal en `path.parent` **después** de esa comprobación. Si un componente del path cambia entre la validación y la escritura (otro proceso sustituye un directorio ancestro por un symlink), la escritura final puede terminar fuera del sandbox.

**Impacto:** race condition (TOCTOU) explotable en entornos multiproceso o multiusuario que comparten el mismo filesystem.

---

### 6. ReDoS sin mitigación en las herramientas de búsqueda del filesystem MCP

`tool_search_files` y `tool_search_with_context` compilan y ejecutan `re.compile(pattern)` con un patrón **totalmente controlado por el cliente/agente**, sin timeout alguno:

```python
_MAX_SEARCH_SECONDS = 30       # Max wall time for regex search   ← nunca usado
```

La constante está declarada pero no se referencia en ningún bucle de búsqueda real (solo `_MAX_SEARCH_FILES` se respeta).

**Impacto:** un patrón con backtracking catastrófico (p. ej. `(a+)+$`) contra cualquier archivo del proyecto cuelga el proceso del servidor indefinidamente.

---

### 7. Sin límite de tamaño de frame en memoria compartida (SHM) ni en TypeScript

`shm.rs::read_frame()` lee un `u32` de longitud directamente de la región de memoria compartida y ejecuta `buf.resize(flen, 0)` sin ningún techo — hasta ~4 GB de asignación de una sola vez.

El transporte por *stream* en Rust sí impone un límite (`MAX_FRAME_SIZE = 16 * 1024 * 1024` en `handshake.rs`), pero esa protección **no se replica** en el transporte SHM, ni existe un equivalente en `frame-assembler.ts` de la implementación TypeScript (sin ninguna constante `MAX`/`limit` en todo el archivo).

**Impacto:** inconsistencia explotable como DoS por agotamiento de memoria, dependiendo del transporte usado.

---

### 8. `Macaroon::decode()` no valida el campo de versión

El propio test `macaroon_wrong_version_decode` documenta el comportamiento: decodificar un macaroon con un byte de versión corrupto (`99`) no falla — se decodifica y **verifica con éxito** igualmente.

```rust
encoded[0] = 99; // corrupt version
let decoded = Macaroon::decode(&encoded).unwrap();
assert_eq!(decoded.version, 99);          // decode acepta cualquier versión
assert!(decoded.verify(&root_key, |_| true));  // y verifica sin problema
```

**Impacto:** imposibilita una migración de protocolo segura en el futuro — no hay forma de rechazar versiones desconocidas o forzar actualizaciones de clientes/servidores.

---

## 🟡 Medias

### 9. Memory leak intencional en la negociación de transporte SHM

`handshake.rs::server_negotiate` y `client_negotiate` usan `std::mem::forget(region)` explícitamente para mantener viva la región `mmap`, documentado en el propio código como leak conocido:

```rust
// NOTE: This leaks memory. A proper fix would wrap ShmRegion
// in Arc and store it in NegotiatedTransport for lifetime mgmt.
// Tracked as #31 in plan-mejoras-2.
std::mem::forget(region);
```

**Impacto:** cada negociación de transporte filtra memoria del proceso. En un servidor de larga duración que negocia muchas conexiones, esto es agotamiento de memoria acumulativo.

---

### 10. Sin mitigación de MITM por defecto en el intercambio de claves

El propio `crypto.rs` admite honestamente la limitación: el intercambio X25519 sin autenticación externa es vulnerable a ataques activos de tipo man-in-the-middle ("opportunistic encryption" en términos del propio comentario del código).

Es una limitación de diseño conocida y documentada, no oculta — pero ningún componente del repositorio (servidores MCP, ejemplos) implementa ninguna de las mitigaciones que el propio código sugiere (TLS, firmas Ed25519, certificate pinning).

**Impacto:** en la práctica, el cifrado no protege contra un atacante activo en ninguno de los despliegues de referencia incluidos en el repositorio.

---

## Notas metodológicas

- Auditoría centrada en: `crypto.rs`, `macaroon.rs`, `handshake.rs`, `shm.rs`, `compress.{rs,py,php}`, `frame.py`, `frame-assembler.ts` y los servidores MCP de `implementations/mcp-servers/filesystem/`.
- Cada hallazgo fue verificado contra el código fuente real (no inferido de la documentación) y, cuando fue posible, confirmado mediante los propios tests del repositorio.
- No se realizó una auditoría exhaustiva de la implementación C#/.NET ni de los módulos `mux.rs` / `stream.rs` / `quic.rs`; quedan fuera del alcance de este informe y podrían contener hallazgos adicionales.
