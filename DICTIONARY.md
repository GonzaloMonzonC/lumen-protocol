# LUMEN - Static Dictionary (128 entries)

These 128 keys are **immutable** and are part of the LUMEN specification.
They occupy IDs `0x00-0x7F`.

---

## Core MCP/RPC (`0x00-0x0F`)

| ID | Key | Primary use |
|----|-----|-------------|
| `0x00` | `tool` | Name of the tool to invoke |
| `0x01` | `arguments` | Tool arguments |
| `0x02` | `result` | Result of an operation |
| `0x03` | `error` | Error response |
| `0x04` | `id` | Request/response identifier |
| `0x05` | `name` | Name (tool, resource, prompt) |
| `0x06` | `description` | Description |
| `0x07` | `content` | Content (resource, message) |
| `0x08` | `text` | Plain text |
| `0x09` | `type` | Data/resource type |
| `0x0A` | `method` | RPC method |
| `0x0B` | `params` | Parameters |
| `0x0C` | `jsonrpc` | JSON-RPC version (compatibility) |
| `0x0D` | `data` | Generic data |
| `0x0E` | `code` | Error code |
| `0x0F` | `message` | Message |

## Input/Output (`0x10-0x1F`)

| ID | Key | Primary use |
|----|-----|-------------|
| `0x10` | `input` | Input data |
| `0x11` | `output` | Output data |
| `0x12` | `stream` | Streaming indicator |
| `0x13` | `uri` | Resource URI |
| `0x14` | `mimeType` | Content MIME type |
| `0x15` | `encoding` | Encoding (utf-8, base64) |
| `0x16` | `language` | Programming language |
| `0x17` | `title` | Title |
| `0x18` | `value` | Value |
| `0x19` | `key` | Key |
| `0x1A` | `path` | File/directory path |
| `0x1B` | `version` | Version |
| `0x1C` | `schema` | JSON schema |
| `0x1D` | `default` | Default value |
| `0x1E` | `required` | Required field |
| `0x1F` | `properties` | Schema properties |

## Resources & Tools (`0x20-0x2F`)

| ID | Key | Primary use |
|----|-----|-------------|
| `0x20` | `resources` | Resource list |
| `0x21` | `tools` | Tool list |
| `0x22` | `prompts` | Prompt list |
| `0x23` | `resource` | Individual resource |
| `0x24` | `prompt` | Individual prompt |
| `0x25` | `handler` | Handler/function |
| `0x26` | `capabilities` | Server capabilities |
| `0x27` | `permissions` | Permissions |
| `0x28` | `scope` | Scope |
| `0x29` | `tags` | Tags |
| `0x2A` | `category` | Category |
| `0x2B` | `icon` | Icon |
| `0x2C` | `metadata` | Metadata |
| `0x2D` | `timestamp` | Timestamp |
| `0x2E` | `status` | Status |
| `0x2F` | `progress` | Progress |

## Errors & Status (`0x30-0x3F`)

| ID | Key | Primary use |
|----|-----|-------------|
| `0x30` | `severity` | Error/log severity |
| `0x31` | `details` | Details |
| `0x32` | `cause` | Root cause |
| `0x33` | `stack` | Stack trace |
| `0x34` | `line` | Line number |
| `0x35` | `column` | Column number |
| `0x36` | `source` | Source |
| `0x37` | `retry` | Retry |
| `0x38` | `timeout` | Timeout |
| `0x39` | `limit` | Limit |
| `0x3A` | `offset` | Offset |
| `0x3B` | `count` | Count |
| `0x3C` | `total` | Total |
| `0x3D` | `page` | Page |
| `0x3E` | `cursor` | Pagination cursor |
| `0x3F` | `next` | Next page |

## LLM / AI (`0x40-0x4F`)

| ID | Key | Primary use |
|----|-------|---------------|
| `0x40` | `model` | AI model |
| `0x41` | `provider` | Provider |
| `0x42` | `temperature` | Sampling temperature |
| `0x43` | `max_tokens` | Maximum tokens to generate |
| `0x44` | `stop` | Stop sequences |
| `0x45` | `frequency_penalty` | Frequency penalty |
| `0x46` | `presence_penalty` | Presence penalty |
| `0x47` | `top_p` | Top-p sampling |
| `0x48` | `logprobs` | Log probabilities |
| `0x49` | `user` | Role: user |
| `0x4A` | `system` | Role: system |
| `0x4B` | `assistant` | Role: assistant |
| `0x4C` | `function` | Function call |
| `0x4D` | `tool_calls` | Tool calls |
| `0x4E` | `finish_reason` | Finish reason |
| `0x4F` | `usage` | Usage statistics |

## HTTP / Web (`0x50-0x5F`)

| ID | Key | Primary use |
|----|-------|---------------|
| `0x50` | `url` | URL |
| `0x51` | `http_method` | HTTP method |
| `0x52` | `headers` | HTTP headers |
| `0x53` | `body` | Request body |
| `0x54` | `query` | Query parameters |
| `0x55` | `http_status` | HTTP status code |
| `0x56` | `cookie` | Cookie |
| `0x57` | `session` | Session |
| `0x58` | `token` | Authentication token |
| `0x59` | `auth` | Authentication |
| `0x5A` | `redirect` | Redirect |
| `0x5B` | `host` | Host |
| `0x5C` | `port` | Port |
| `0x5D` | `origin` | Origin |
| `0x5E` | `referrer` | Referrer |
| `0x5F` | `agent` | User-Agent |

## File System (`0x60-0x6F`)

| ID | Key | Primary use |
|----|-------|---------------|
| `0x60` | `filename` | File name |
| `0x61` | `directory` | Directory |
| `0x62` | `extension` | File extension |
| `0x63` | `size` | Size in bytes |
| `0x64` | `modified` | Modification date |
| `0x65` | `created` | Creation date |
| `0x66` | `accessed` | Access date |
| `0x67` | `mode` | File permissions |
| `0x68` | `owner` | Owner |
| `0x69` | `group` | Group |
| `0x6A` | `symlink` | Symbolic link |
| `0x6B` | `binary` | Binary indicator |
| `0x6C` | `base64` | Base64 data |
| `0x6D` | `hash` | Hash/checksum |
| `0x6E` | `algorithm` | Algorithm |
| `0x6F` | `chunk` | Chunk |

## Operations (`0x70-0x7F`)

| ID | Key | Primary use |
|----|-------|---------------|
| `0x70` | `execute` | Execute |
| `0x71` | `read` | Read |
| `0x72` | `write` | Write |
| `0x73` | `delete` | Delete |
| `0x74` | `update` | Update |
| `0x75` | `create` | Create |
| `0x76` | `search` | Search |
| `0x77` | `list` | List |
| `0x78` | `get` | Get |
| `0x79` | `set` | Set |
| `0x7A` | `watch` | Watch |
| `0x7B` | `subscribe` | Subscribe |
| `0x7C` | `notify` | Notify |
| `0x7D` | `cancel` | Cancel |
| `0x7E` | `pause` | Pause |
| `0x7F` | `resume` | Resume |

---

## Session Dictionary (IDs `0x80-0xFE`)

127 dynamic slots negotiated per session. Each endpoint can register its own
frequent keys via `DICT_SYNC` (frame `0x07`) or directly through the API:

- `register_session_key(key, id)` - registers a key in a slot
- `unregister_session_key(id)` - frees a slot
- `init_session_dict(entries)` - initial load from `(id, key)` pairs
- `clear_session_dict()` - frees all slots
- `session_dict_size()` - number of registered entries

Implemented in all 5 languages: Rust (`OnceLock<RwLock<SessionDict>>`), TypeScript,
Python, C#, and PHP.

---

## ID 0xFF - "RAW" Sentinel

When a key is **not** present in either the static dictionary or the session dictionary,
it is transmitted as plain text. `0xFF` acts as a sentinel.

---

*Entries `0x80-0xFE` reserved for the session dictionary (dynamic).*
