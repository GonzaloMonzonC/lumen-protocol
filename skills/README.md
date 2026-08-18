# Skills de lumen para agentes Hermes

Skills operativos para agentes Hermes que trabajen con lumen-protocol.

## Instalación

Copiar la carpeta del skill a la carpeta de skills de Hermes:

```bash
# Windows
cp -r skills/lumen-mcp "$LOCALAPPDATA/hermes/skills/"

# Linux/macOS
cp -r skills/lumen-mcp ~/.hermes/skills/
```

O referenciarlo desde el repo si el agente soporta rutas externas.

## Disponibles

| Skill | Contenido |
|---|---|
| `lumen-mcp` | Operación y diagnóstico de los 4 MCP servers: framing Content-Length, keepalive/ping, ReadFile nativo (Windows), wrappers `_adapt_pos`, probe de diagnóstico, pitfalls conocidos |

Relacionado: `lumen-protocol` (boot del stack completo, MVM, PDB) —
disponible localmente en Hermes, documentado en `docs/nueva-instalacion/`.
