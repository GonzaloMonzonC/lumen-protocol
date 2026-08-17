# Extensibilidad del MVM — análisis objetivo (caso de uso Cadences Lab)

*17 de agosto de 2026 · Decisión de Gonzalo: no dejarse llevar por lo que el código ofrece;
punto de vista objetivo para NUESTRO caso de uso. No somos GT.M, ni MUMPS, ni Python:
somos un ecosistema de agentes con necesidades propias.*

## 1 · Inventario: los bits que YA tenemos (sin escribir una línea)

| Pieza | Dónde | Qué hace | Uso real |
|---|---|---|---|
| **Device 7 — LLM nativo** | `lumen-mvm/device7` (en lib.rs) | `O 7:"model"` → fork+await con yield | poli_llm, smith, todos los agentes |
| **Device 8 — HTTP client** | `device8.rs` | `O 8:"GET url"` async (reqwest+tokio), no bloquea | poli_http, el M habla con APIs |
| **Device 9 — Webhook server** | `device9.rs` | `O 9:` → cola compartida de mensajes | entradas externas al MVM |
| **Device 11 — Output** | lib.rs | el `W` del M a stdout/estado | todo |
| **FFI C ABI** | `m-light/ffi.rs` | "Stable JSON C ABI for Python and other language bindings" — sesiones persistentes | el poli_server (Python) ejecuta M y viceversa |
| **Host — PDB/DDP** | `host.rs` | globals, transacciones, locks, rutinas | el M escribe en la PDB (^ROUTINE, ^KANBAN...) |
| **Package manager** | `package_manager.rs` | `IMPORT("lumen-std:1.2.3")` desde registry | instalación de rutinas M |
| **WASM** | `m-light/wasm.rs` | sandbox WebAssembly | potencial: módulos de terceros aislados |
| **Puente Python del poli_server** | poli_server.py | el MCP expone `poli_llm/poli_http/poli_exec` | el M puede llamar Python arbitrario hoy |
| **Puente MVM→Quantum** | LQ + vm-api | rutina M → QPU real (Tuna-9) | Dánae, el cron de las 08:00 |

## 2 · El caso de uso real (lo que DE VERDAD necesitamos)

**La distinción que nos hace únicos: la replicación infinita.**
GT.M, MUMPS y Python nacieron monohost: su extensión ($ZF, callouts, módulos) asume
una máquina local con procesos locales. Nosotros podemos replicarnos entre servidores
por Internet y crecer al infinito — los sistemas antiguos no podían tenerlo en cuenta.
Consecuencia objetiva: **toda capacidad nueva debe ser agnóstica del host** — funcionar
igual en cualquier réplica. Un "device de subprocesos locales" sería ANTI-replicación
(rompe en cuanto el MVM vive en otro servidor). El FFI (JSON C ABI), el HTTP (device 8)
y el WASM (sandbox portable) SÍ son agnósticos del host → son los caminos correctos.

Nuestro ecosistema no necesita:
- ❌ Compilar rutinas C para drivers de hardware (el caso de $ZF en GT.M hospitalario)
- ❌ Callouts de bajo nivel para rendimiento de cómputo local (no tenemos ese cuello)
- ❌ Un device nuevo que lance subprocesos Python/Node (¡el puente Python ya lo hace!)

Nuestro ecosistema SÍ necesita:
- ✅ Hablar con LLMs → **cubierto** (device 7 + poli_llm)
- ✅ HTTP/APIs externas → **cubierto** (device 8 + poli_http)
- ✅ Persistir en la PDB → **cubierto** (host + DDP)
- ✅ Ejecutar análisis/externa (numpy, genomas, etc.) → **cubierto** (puente Python)
- ✅ Añadir rutinas M nuevas → **cubierto** (package manager + siembra)
- ⏳ Módulos de TERCEROS sin tocar el host → **WASM** (sandbox portable entre réplicas)
- ✅ Saber qué hay fuera → **^EXT** (registro canónico, sembrado el 17-08-2026)

## 3 · Conclusión

**La extensibilidad del MVM ya está resuelta** por la combinación de: devices (LLM/HTTP/webhook)
+ FFI (Python) + host (PDB) + package manager (rutinas) + WASM (sandbox).

**No hace falta un "device 10" de subprocesos**: duplicaría el puente Python con peor
gestión de gas/timeout y más superficie de ataque. El criterio objetivo para añadir
capacidad nueva:

1. ¿Hay un caso de uso real de un agente que lo exija? (hoy: no)
2. ¿Lo cubre el FFI/puente Python? (casi siempre: sí)
3. ¿Es para terceros? → WASM (no un device)

**Lo único pendiente es documental**: un registro `^EXT(nombre) = {tipo, ruta, desc}` que
enumere los módulos externos disponibles (numpy, biopython, node, etc.) como METADATO del
ecosistema — para que cualquier agente sepa qué hay fuera sin tocar el motor M.

*— Hermes, con la corrección de Gonzalo: mirar bien lo que ya tenemos antes de construir.*
