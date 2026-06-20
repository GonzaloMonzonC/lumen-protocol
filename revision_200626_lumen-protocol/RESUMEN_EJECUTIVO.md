# 🔬 lumen-protocol - Resumen Ejecutivo

**Total archivos:** 59 (~180 KB)

## 📚 Documentación Clave

| Archivo | Tamaño | Descripción |
|---------|--------|-------------|
| README.md | 11 KB | Protocolo binario para MCP - reemplaza JSON-RPC |
| README_EXT.md | 61 KB | Documentación extendida completa |
| PAPER.md | 26 KB | Paper académico del protocolo |
| RFC_LUMEN.md | 66 KB | Especificación RFC detallada |
| SPEC_DEV.md | 21 KB | Especificación de desarrollo |
| HERMES_INTEGRATION.md | 13 KB | Integración con Hermes Agent |
| DICTIONARY.md | 6 KB | Diccionario de compresión estático (128 keys) |

## 🔑 Características Técnicas

- **Overhead:** 3-6 bytes vs 40-60 bytes JSON-RPC
- **Streaming:** STREAM_DATA + STREAM_INIT frames
- **Multiplex:** 16 frame types (REQUEST, RESPONSE, NOTIFY, STREAM_DATA, SCHEMA_PATCH, etc.)
- **Security:** Macaroons + ChaCha20-Poly1305
- **Compression:** Static dictionary (128) + Session dictionary (127)

## 📦 Implementaciones

- Rust (reference), TypeScript, Python, PHP, C#
