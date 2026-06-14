# LUMEN — Diccionario Estático (128 entradas)

Estas 128 claves son **inmutables** y forman parte de la especificación LUMEN.
Ocupan los IDs `0x00–0x7F`.

---

## Core MCP/RPC (`0x00–0x0F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x00` | `tool` | Nombre de herramienta a invocar |
| `0x01` | `arguments` | Argumentos de la herramienta |
| `0x02` | `result` | Resultado de una operación |
| `0x03` | `error` | Error response |
| `0x04` | `id` | Identificador de request/response |
| `0x05` | `name` | Nombre (herramienta, recurso, prompt) |
| `0x06` | `description` | Descripción |
| `0x07` | `content` | Contenido (de recurso, mensaje) |
| `0x08` | `text` | Texto plano |
| `0x09` | `type` | Tipo de dato/recurso |
| `0x0A` | `method` | Método RPC |
| `0x0B` | `params` | Parámetros |
| `0x0C` | `jsonrpc` | Versión JSON-RPC (compatibilidad) |
| `0x0D` | `data` | Datos genéricos |
| `0x0E` | `code` | Código de error |
| `0x0F` | `message` | Mensaje |

## Input/Output (`0x10–0x1F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x10` | `input` | Datos de entrada |
| `0x11` | `output` | Datos de salida |
| `0x12` | `stream` | Indicador de streaming |
| `0x13` | `uri` | URI de recurso |
| `0x14` | `mimeType` | Tipo MIME del contenido |
| `0x15` | `encoding` | Codificación (utf-8, base64) |
| `0x16` | `language` | Lenguaje de programación |
| `0x17` | `title` | Título |
| `0x18` | `value` | Valor |
| `0x19` | `key` | Clave |
| `0x1A` | `path` | Ruta de archivo/directorio |
| `0x1B` | `version` | Versión |
| `0x1C` | `schema` | Esquema JSON |
| `0x1D` | `default` | Valor por defecto |
| `0x1E` | `required` | Campo requerido |
| `0x1F` | `properties` | Propiedades de esquema |

## Resources & Tools (`0x20–0x2F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x20` | `resources` | Lista de recursos |
| `0x21` | `tools` | Lista de herramientas |
| `0x22` | `prompts` | Lista de prompts |
| `0x23` | `resource` | Recurso individual |
| `0x24` | `prompt` | Prompt individual |
| `0x25` | `handler` | Manejador/Función |
| `0x26` | `capabilities` | Capacidades del servidor |
| `0x27` | `permissions` | Permisos |
| `0x28` | `scope` | Ámbito/Scope |
| `0x29` | `tags` | Etiquetas |
| `0x2A` | `category` | Categoría |
| `0x2B` | `icon` | Icono |
| `0x2C` | `metadata` | Metadatos |
| `0x2D` | `timestamp` | Marca de tiempo |
| `0x2E` | `status` | Estado |
| `0x2F` | `progress` | Progreso |

## Errors & Status (`0x30–0x3F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x30` | `severity` | Severidad de error/log |
| `0x31` | `details` | Detalles |
| `0x32` | `cause` | Causa raíz |
| `0x33` | `stack` | Stack trace |
| `0x34` | `line` | Número de línea |
| `0x35` | `column` | Número de columna |
| `0x36` | `source` | Fuente |
| `0x37` | `retry` | Reintento |
| `0x38` | `timeout` | Timeout |
| `0x39` | `limit` | Límite |
| `0x3A` | `offset` | Desplazamiento |
| `0x3B` | `count` | Cantidad |
| `0x3C` | `total` | Total |
| `0x3D` | `page` | Página |
| `0x3E` | `cursor` | Cursor de paginación |
| `0x3F` | `next` | Siguiente página |

## LLM / AI (`0x40–0x4F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x40` | `model` | Modelo de IA |
| `0x41` | `provider` | Proveedor |
| `0x42` | `temperature` | Temperatura de sampling |
| `0x43` | `max_tokens` | Máximo de tokens a generar |
| `0x44` | `stop` | Secuencias de parada |
| `0x45` | `frequency_penalty` | Penalización por frecuencia |
| `0x46` | `presence_penalty` | Penalización por presencia |
| `0x47` | `top_p` | Top-p sampling |
| `0x48` | `logprobs` | Log probabilities |
| `0x49` | `user` | Rol: usuario |
| `0x4A` | `system` | Rol: sistema |
| `0x4B` | `assistant` | Rol: asistente |
| `0x4C` | `function` | Llamada a función |
| `0x4D` | `tool_calls` | Llamadas a herramientas |
| `0x4E` | `finish_reason` | Motivo de finalización |
| `0x4F` | `usage` | Estadísticas de uso |

## HTTP / Web (`0x50–0x5F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x50` | `url` | URL |
| `0x51` | `http_method` | Método HTTP |
| `0x52` | `headers` | Cabeceras HTTP |
| `0x53` | `body` | Cuerpo de petición |
| `0x54` | `query` | Parámetros de consulta |
| `0x55` | `http_status` | Código de estado HTTP |
| `0x56` | `cookie` | Cookie |
| `0x57` | `session` | Sesión |
| `0x58` | `token` | Token de autenticación |
| `0x59` | `auth` | Autenticación |
| `0x5A` | `redirect` | Redirección |
| `0x5B` | `host` | Host |
| `0x5C` | `port` | Puerto |
| `0x5D` | `origin` | Origen |
| `0x5E` | `referrer` | Referrer |
| `0x5F` | `agent` | User-Agent |

## File System (`0x60–0x6F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x60` | `filename` | Nombre de archivo |
| `0x61` | `directory` | Directorio |
| `0x62` | `extension` | Extensión de archivo |
| `0x63` | `size` | Tamaño en bytes |
| `0x64` | `modified` | Fecha de modificación |
| `0x65` | `created` | Fecha de creación |
| `0x66` | `accessed` | Fecha de acceso |
| `0x67` | `mode` | Permisos de archivo |
| `0x68` | `owner` | Propietario |
| `0x69` | `group` | Grupo |
| `0x6A` | `symlink` | Enlace simbólico |
| `0x6B` | `binary` | Indicador binario |
| `0x6C` | `base64` | Datos en Base64 |
| `0x6D` | `hash` | Hash/Checksum |
| `0x6E` | `algorithm` | Algoritmo |
| `0x6F` | `chunk` | Fragmento |

## Operaciones (`0x70–0x7F`)

| ID | Clave | Uso principal |
|----|-------|---------------|
| `0x70` | `execute` | Ejecutar |
| `0x71` | `read` | Leer |
| `0x72` | `write` | Escribir |
| `0x73` | `delete` | Eliminar |
| `0x74` | `update` | Actualizar |
| `0x75` | `create` | Crear |
| `0x76` | `search` | Buscar |
| `0x77` | `list` | Listar |
| `0x78` | `get` | Obtener |
| `0x79` | `set` | Establecer |
| `0x7A` | `watch` | Observar |
| `0x7B` | `subscribe` | Suscribirse |
| `0x7C` | `notify` | Notificar |
| `0x7D` | `cancel` | Cancelar |
| `0x7E` | `pause` | Pausar |
| `0x7F` | `resume` | Reanudar |

---

## Diccionario de Sesión (IDs `0x80–0xFE`)

127 slots dinámicos negociados por sesión. Cada extremo puede registrar sus propias
claves frecuentes vía `DICT_SYNC` (frame `0x07`) o directamente mediante la API:

- `register_session_key(key, id)` — registra una clave en un slot
- `unregister_session_key(id)` — libera un slot
- `init_session_dict(entries)` — carga inicial desde pares `(id, key)`
- `clear_session_dict()` — libera todos los slots
- `session_dict_size()` — número de entradas registradas

Implementado en los 5 lenguajes: Rust (`OnceLock<RwLock<SessionDict>>`), TypeScript,
Python, C#, y PHP.

---

## ID 0xFF — Centinela "RAW"

Cuando una clave **no** está presente en el diccionario estático ni en el de sesión,
se transmite en texto plano. `0xFF` actúa como centinela.

---

*Entradas `0x80–0xFE` reservadas para el diccionario de sesión (dinámico).*
