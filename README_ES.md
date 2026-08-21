<p align="center">
  <br>
  <h1 align="center">◆ ECOS</h1>
  <p align="center"><strong>Edge Cognitive Operating System — Sistema Operativo Cognitivo Edge</strong></p>
  <p align="center"><em>LUMEN — el transporte binario abierto en su núcleo</em></p>
  <p align="center">
    El resto del mundo intenta hacer correr sociedades de IA sobre arquitecturas web lentas de los años 2010.
    <br>
    ECOS las hace correr sobre <strong>memoria binaria, jerárquica y zero-copy en el edge</strong>.
  </p>
  <br>
</p>

<p align="center">
  <strong>Este repo es el metal abierto de ECOS:</strong> protocolo binario, transporte zero-copy, estado cognitivo PDB/MVM, 115 herramientas MCP.
  <br>
  <a href="QUICKSTART_ES.md"><strong>🚀 Empezar aquí</strong></a> · <a href="QUICKSTART.md">Quickstart (EN)</a> &nbsp;|&nbsp;
  <a href="INSTALL.md"><strong>🚀 Instalar en Hermes Agent</strong></a> &nbsp;|&nbsp;
  <a href="docs/COGNITIVE_OS.md"><strong>🧠 Docs del Cognitive OS</strong></a> &nbsp;|&nbsp;
  <strong>✅ SHM zero-copy Nivel 2 · 55-80% menos tráfico · 4 servidores MCP · funciona con Hermes</strong>
</p>

---

## 🌍 La visión ECOS — por qué existe esto

> *"El mundo intenta hacer correr sociedades de IA sobre arquitecturas web lentas de los años 2010. Nosotros hemos construido un motor de ejecución binario y jerárquico en el edge, donde los agentes no son scripts conectados por APIs, sino hilos cognitivos que comparten la misma memoria física y se auditan mutuamente en tiempo real."*

Tres apuestas. Tres muros con los que la industria va a chocar:

**1. El colapso del I/O (el problema JSON-RPC).** Mientras un humano habla con un LLM, la latencia del JSON es invisible. Cuando 10 agentes debaten, extraen datos, revisan esquemas y hacen retrospectivas, el sistema se vuelve I/O-bound — el cable, no el modelo, es el cuello de botella. El futuro inevitable de la orquestación multi-agente es el **transporte binario y la memoria compartida zero-copy en el edge**. LUMEN ya lo trae, con datos: **55-80% menos tráfico, SHM Nivel 2 (ring buffers mmap, cero copias de kernel, latencia sub-ms), 20K llamadas/seg en stress tests empresariales, streams de tokens 46% más pequeños**.

**2. El fin del parche de la "memoria RAG".** Dar memoria a los agentes inyectando bases vectoriales a la fuerza en arquitecturas stateless es un parche — los vectores son un índice, no una memoria. El futuro real de la cognición artificial es el **estado transaccional, estructurado y jerárquico que actúa como memoria cognitiva nativa**: una máquina virtual en disco donde las decisiones, los diccionarios y los patrones de comportamiento viven intrínsecamente en la infraestructura. Eso es **PDB + MVM**: globals con herencia MUMPS (1966), `$LOCK`, auto-índices `^IDX`, triggers `ON SET`/`ON KILL`, WAL, 15 μs/GET — y una Máquina Virtual M ejecutando procesos autónomos y persistentes.

**3. Software Factory, no un framework para developers.** El mainstream está secuestrado por Python/TypeScript, y el humano no debería tener que tocar el metal. ECOS es el **Sistema Operativo Cognitivo Edge** donde el humano actúa como Director de Operaciones y los agentes especializados ejecutan y garantizan la calidad conductual del sistema. Este repo es la capa abierta de ese sistema; la orquestación y la lógica de negocio viven por encima.

**Mapa de capas**

| Capa | Qué es | ¿Abierta aquí? |
|------|--------|----------------|
| Protocolo LUMEN + transportes | Wire binario (Hyb128), SHM zero-copy, datagram, QUIC, ChaCha20-Poly1305, macaroons | ✅ **Este repo (MIT)** |
| PDB + M-Light + MVM | Estado cognitivo jerárquico, evaluador M, procesos M autónomos | ✅ **Este repo** |
| Servidores MCP (115 tools) | Filesystem, web, thinking, PDB — listos para Hermes Agent | ✅ **Este repo** |
| Orquestación ECOS | Equipos multi-agente, consolidación de memoria, voz, Lab | 🔒 Capa propietaria |

**Qué puedes hacer hoy aquí:** sustituir tu wire MCP JSON-RPC por uno binario (55-80% más pequeño), dar a tu agente un cerebro jerárquico persistente (PDB) y ejecutar procesos M autónomos en el edge (MVM) — todo sin claves de API.

---

## ¿Por qué? (resumen técnico)

JSON-RPC sobre stdio es el estándar MCP. Funciona. Pero a escala, duele — y la tabla completa está en el [README principal (EN)](README.md). En una línea: **el wire JSON pierde contra el binario en tamaño, copias de kernel, streaming, seguridad y fiabilidad en Windows**; LUMEN gana en los cinco frentes con implementaciones en Rust, TypeScript, Python, PHP, C# y WASM.

Benchmarks reales: `tools/list` con 106 tools pasa de 39.7 KB (JSON-RPC) a 24.8 KB (LUMEN, **-37%**); un stream de 10K tokens de LLM, de 1009 KB a 543 KB (**-46%**); un loop de agente de 30 turnos, de 6.4 KB a 3.3 KB (**-48%**). Ver [docs/BENCHMARKS.md](docs/BENCHMARKS.md) y [informe global de cognitive benchmarks](implementations/mcp-servers/pdb/bench-results/INFORME_GLOBAL.md).

---

## Guía rápida

```bash
# 📦 Paquetes publicados (sin clonar)
pip install lumen-mcp           # Python
npm install @gonzalomonzonc/mcp-transport  # TypeScript

# O desde fuente:
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

# Python
cd implementations/python && pip install -e . && cd ../..

# TypeScript
cd implementations/typescript && npm install && npm run build && cd ../..

# Rust
cd implementations/rust && cargo test && cargo bench && cd ../..

# Registrar los 4 servidores MCP en Hermes Agent (115 tools):
bash scripts/setup_hermes_mcp.sh    # Windows: scripts\setup_hermes_mcp.bat
```

---

## Estado y hoja de ruta (resumen)

✅ **Construido y funcionando**: framing Hyb128 (1/3/5B), diccionario estático 128 keys, diccionario de sesión LRU, compresión binaria, **115 tools MCP**, **SHM zero-copy Nivel 2**, plugin `lumen-shm-bridge` para Hermes, **M-Light** (evaluador M, ~70% MSM STU), **MVM** (procesos M autónomos), cifrado ChaCha20-Poly1305, X25519, macaroons, canales MUX, **QUIC (L4)**, objetivo WASM (22 KB gzipped), Cognitive OS Rust (loop de agente, PdbHost nativo redb, HttpLlmEngine, persistencia `^PROCESSES`, 15/15 tests).

🚧 **En desarrollo**: mesh multi-máquina LUMEN-over-WebSocket en Cloudflare (Fase E), publicar el protocolo como estándar abierto universal.

La tabla completa (incluyendo los 12 spec/code mismatches, todos resueltos salvo C# frame layer y tests Rust) está en el [README principal (EN)](README.md).

---

## Docs

| Doc | Contenido |
|-----|-----------|
| [docs/INDEX.md](docs/INDEX.md) | 📍 Mapa de documentación — empieza aquí |
| [docs/SSOT_ARQUITECTURA.md](docs/SSOT_ARQUITECTURA.md) | 🔀 Fuente de Verdad Única: dónde vive cada dato, wire DDP, jerarquía MVM |
| [docs/COGNITIVE_OS.md](docs/COGNITIVE_OS.md) | Arquitectura del Cognitive OS, referencia de 115 tools |
| [docs/PLAN_EVOLUCION.md](docs/PLAN_EVOLUCION.md) | Plan de evolución PDB + M-Light + MVM por ROI |
| [docs/BENCHMARKS.md](docs/BENCHMARKS.md) | Benchmarks consolidados (3.407 llamadas/seg) |
| [RFC_LUMEN.md](RFC_LUMEN.md) | RFC del protocolo en formato IETF |
| [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) | Guía de integración con Hermes Agent |
| [README_EXT.md](README_EXT.md) | Spec del protocolo, benchmarks, arquitectura (EN) |

---

## Licencia

MIT — ver [LICENSE](LICENSE)

---

<p align="center">
  <sub>ECOS — Edge Cognitive Operating System · LUMEN · <em>Tu wire MCP. Más pequeño. Más rápido. Más seguro.</em></sub>
</p>
