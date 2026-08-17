# LUMEN + Hermes Agent — Guía de Instalación

> **Estado**: ✅ Verificado — **115 tools en 4 servidores MCP** (filesystem, web, thinking, PDB)
> **PR**: [NousResearch/hermes-agent#47740](https://github.com/NousResearch/hermes-agent/pull/47740)
> **Transporte**: JSON-RPC stdio (MCP estándar) — la ruta verificada con el cliente MCP de Hermes

---

## Instalación Rápida (2 minutos)

### Opción A — Script de setup (recomendado)

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

# macOS / Linux / git-bash (Windows)
bash scripts/setup_hermes_mcp.sh

# Windows (cmd/PowerShell)
scripts\setup_hermes_mcp.bat
```

El script crea el venv, instala `lumen-mcp`, registra los 4 servidores con
`hermes mcp add` y verifica con `hermes mcp list`.

### Opción B — Manual

#### 1. Clonar el repositorio

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol
```

#### 2. Crear venv + instalar el paquete Python de LUMEN

```bash
python -m venv .venv
# Windows:
.venv\Scripts\pip install -e implementations\python
# macOS / Linux:
.venv/bin/pip install -e implementations/python
```

> Los servidores MCP deben ejecutarse con el python de este venv — importan el paquete `lumen`.

#### 3. Registrar los 4 servidores MCP

```bash
hermes mcp add lumen-filesystem --command "C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe" --args "C:/ruta/abs/lumen-protocol/implementations/mcp-servers/filesystem/server.py"
hermes mcp add lumen-web        --command "C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe" --args "C:/ruta/abs/lumen-protocol/implementations/mcp-servers/web/server.py"
hermes mcp add lumen-thinking   --command "C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe" --args "C:/ruta/abs/lumen-protocol/implementations/mcp-servers/thinking/server.py"
hermes mcp add lumen-pdb        --command "C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe" --args "C:/ruta/abs/lumen-protocol/implementations/mcp-servers/pdb/server.py"
```

(macOS/Linux: usa `.venv/bin/python` y `/ruta/abs/...`.)

Bloque equivalente en `~/.hermes/config.yaml` (JSON-RPC stdio plano — **sin
necesidad de claves `transport: lumen`**; el transporte binario LUMEN es opcional, ver abajo):

```yaml
mcp_servers:
  lumen-filesystem:
    command: C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/ruta/abs/lumen-protocol/implementations/mcp-servers/filesystem/server.py]
    enabled: true
  lumen-web:
    command: C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/ruta/abs/lumen-protocol/implementations/mcp-servers/web/server.py]
    enabled: true
  lumen-thinking:
    command: C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/ruta/abs/lumen-protocol/implementations/mcp-servers/thinking/server.py]
    enabled: true
  lumen-pdb:
    command: C:/ruta/abs/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/ruta/abs/lumen-protocol/implementations/mcp-servers/pdb/server.py]
    enabled: true
```

#### 4. Reiniciar Hermes

```
/reset
```

#### 5. Verificar

```bash
hermes mcp list
```

Los 4 servidores deben mostrar `✓ enabled`. Luego, en el catálogo de
herramientas del agente, busca `mcp__lumen_*` — las 115 tools aparecerán ahí.

---

## Qué Obtienes

| Servidor | Tools | Funcionalidades Clave |
|----------|-------|-----------------------|
| **Filesystem** | 13 | Lecturas múltiples, búsqueda con contexto, streaming, métricas de salud, sin dependencia de shell |
| **Web** | 2 | Búsqueda + extracción en 1 llamada, sin API key |
| **Thinking** | 81 | Razonamiento externo, kanban/nichos, wiki, patrones, decisiones, watches de PDB, dashboards |
| **PDB** | 19 | Almacén persistente `^ns(key)=value`, búsqueda vectorial (KNN), registro de apps MVM, notificaciones |
| **Total** | **115** | 0 API keys requeridas |

---

## Opcional: Transporte binario LUMEN nativo (50-80% menos wire)

Para aún más compresión, los servidores también traen un modo binario nativo
(`server_native.py` + `transport: lumen`). Esta ruta es **experimental** con el
cliente MCP actual de Hermes — la configuración JSON-RPC stdio de arriba es la
verificada y recomendada:

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args:
      - "ruta/a/lumen-protocol/implementations/mcp-servers/filesystem/server_native.py"
    transport: lumen
    lumen_force_json_rpc: false  # modo binario nativo
```

---

## Opcional: Ejecutar el MVM Web Engine + DDP Server (`vm_api.py`) localmente

El ecosistema también trae un servidor HTTP local (puerto `8081`) que ejecuta
código M en el **MVM Rust** y sirve el sync DDP (`/ddp/pull`, `/ddp/push`, `/ddp/allocate`).

> ⚠️ **Requisito de primera vez**: el MVM Rust es una DLL (`lumen_mlight.dll`) que
> **no** está commiteada. Sin ella, el primer arranque lanza un `cargo build
> --release` bloqueante (~4 min) que parece un cuelgue. Compílala una vez:

```bash
cd implementations/rust/lumen-m-light
cargo build --release --features minreq     # → target/release/lumen_mlight.dll
cd ../../..
```

Luego arranca el server:

```bash
# Windows
.venv/Scripts/python.exe implementations/python/pdb-sync/vm_api.py 8081
# macOS / Linux
.venv/bin/python implementations/python/pdb-sync/vm_api.py 8081

curl http://localhost:8081/ddp/health       # → {"ok": true, "ddp": "local", "hmac": false}
```

Auth opcional: `export DDP_HMAC_KEY=<secreto>` (sin clave = modo local, sin
firma). Mapa completo de endpoints, contrato de `/vm/execute`, audit y
solución de problemas: **[docs/GUIA_VM_API.md](docs/GUIA_VM_API.md)**.

---

## Solución de Problemas

### "El servidor MCP no pudo conectarse" / el discovery se cuelga

El cliente MCP de Hermes exige un handshake `initialize` + `tools/list`
completo. El servidor PDB tenía un bug que colgaba el discovery; **ya está
corregido en el repo** (commit `7499c3a`, `pdb/server.py`). Si tienes un
checkout antiguo:

```bash
git pull
```

Y prueba el servidor manualmente:

```bash
# Windows
.venv\Scripts\python.exe implementations\mcp-servers\pdb\server.py
# macOS / Linux
.venv/bin/python implementations/mcp-servers/pdb/server.py
```

### `pdb_set` devuelve "unable to open database file"

La base de datos ahora vive en `implementations/mcp-servers/pdb/lumen-pdb.db`
(dentro del repo, se crea automáticamente — ver `_paths.py`). Antes apuntaba a
una ruta hardcodeada de la máquina del desarrollador. Puedes sobrescribirla con
las variables de entorno `PDB_PATH` o `PDB_DB` (útil para benchmarks):

```bash
export PDB_PATH=/ruta/a/mi-pdb.db
```

### "LUMEN SDK no disponible"

```bash
.venv\Scripts\pip install -e implementations\python   # o .venv/bin/pip en macOS/Linux
```

### Servidor registrado pero 0 tools

- Asegúrate de que `command` apunte al python **del venv** (no al python del sistema).
- Revisa los logs de Hermes: `cat ~/AppData/Local/hermes/logs/mcp-stderr.log | tail -20`
- Reinicia Hermes con `/reset` tras registrar.

---

## Ver También

- [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) — Guía completa de integración
- [TOOLS_GUIDE.md](implementations/mcp-servers/docs/TOOLS_GUIDE.md) — Cuándo usar cada herramienta
- [RETROSPECTIVE_ES.md](implementations/mcp-servers/RETROSPECTIVE_ES.md) — Comparativa antes/después
