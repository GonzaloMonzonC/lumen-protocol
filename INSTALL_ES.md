# LUMEN + Hermes Agent — Guía de Instalación

> **Estado**: ✅ Producción — 29 tools en 3 servidores MCP.  
> **PR**: [NousResearch/hermes-agent#47740](https://github.com/NousResearch/hermes-agent/pull/47740)  
> **LUMEN binario nativo**: ✅ Funcionando en Windows, Mac, Linux

---

## Instalación Rápida (2 minutos)

### 1. Clonar el repositorio
```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol
```

### 2. Instalar paquete Python de LUMEN
```bash
pip install -e implementations/python
```

### 3. Añadir servidores MCP a la configuración de Hermes

Editar `~/.hermes/config.yaml` (Windows: `%APPDATA%/hermes/config.yaml`):

```yaml
mcp_lumen:
  enabled: true

mcp_servers:
  lumen_filesystem:
    command: "python"
    args:
      - "ruta/a/lumen-protocol/implementations/mcp-servers/filesystem/server.py"
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true

  lumen_web:
    command: "python"
    args:
      - "ruta/a/lumen-protocol/implementations/mcp-servers/web/server.py"
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true

  lumen_thinking:
    command: "python"
    args:
      - "ruta/a/lumen-protocol/implementations/mcp-servers/thinking/server.py"
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true
```

### 4. Reiniciar Hermes
```
/reset
```

### 5. Verificar

Tras el reset, el agente mostrará:
```
⚡ LUMEN tools active: filesystem (9), web (2), thinking (18) — 29 total
```

---

## Qué Obtienes

| Servidor | Tools | Wire Savings | Funcionalidades Clave |
|----------|-------|-------------|----------------------|
| **Filesystem** | 9 | 32-70% | Lectura múltiple, búsqueda con contexto, streaming, métricas |
| **Web** | 2 | 40-50% | Búsqueda + extracción en 1 llamada, sin API key |
| **Thinking** | 18 | 60-80% | Razonamiento externo, registro de asunciones, modelo mental, preservación de contexto |

---

## LUMEN Binario Nativo (50-80% wire savings)

Para aún más compresión, usar el servidor binario nativo:

```yaml
mcp_servers:
  lumen_filesystem:
    args:
      - "ruta/a/lumen-protocol/implementations/mcp-servers/filesystem/server_native.py"
    transport: lumen
    lumen_force_json_rpc: false  # Modo binario nativo
```

---

## Solución de Problemas

### "El servidor MCP no pudo conectarse"
```bash
# Revisar logs
cat ~/AppData/Local/hermes/logs/mcp-stderr.log | tail -20

# Probar el servidor manualmente
python implementations/mcp-servers/filesystem/server.py
```

### "LUMEN SDK no disponible"
```bash
pip install -e implementations/python
```

### Windows: el servidor no responde
Asegurar que `lumen_force_json_rpc: true` esté configurado si usas `server.py` (wrapper JSON-RPC).
Usar `server_native.py` con `lumen_force_json_rpc: false` para modo binario nativo.

---

## Ver También

- [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) — Guía completa de integración
- [TOOLS_GUIDE.md](implementations/mcp-servers/TOOLS_GUIDE.md) — Cuándo usar cada herramienta
- [RETROSPECTIVE_ES.md](implementations/mcp-servers/RETROSPECTIVE_ES.md) — Comparativa antes/después
