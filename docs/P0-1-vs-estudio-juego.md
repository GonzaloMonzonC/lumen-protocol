# P0-1 visto desde el estudio del juego — y un hallazgo que lo amplía

**Fecha:** 2026-10-19 · **Fuente:** `analisis/estudio-lumen-juego-pdb-mvm-2026-10/` (26 docs) + código real

---

## Resumen

> **P0-1 no se rompe, pero se queda corto: el catálogo MCP no es el único inventario de tools del stack.**
> La MVM tiene el suyo — `^TOOLS` + `$DEVICE("tool:list")` + `%AGENTE.m` (bucle de tool-calling completo,
> DISENO-4, 04-oct-2026). Podar el catálogo de Hermes **no poda la superficie real del stack**: la poda de uno.

---

## 1. El hallazgo: hay DOS catálogos de tools — y su estado en OSS es asimétrico

### Estado real en el repo OSS (verificado con `git ls-files`)

| Pieza | ¿En el repo OSS? | Evidencia |
|---|---|---|
| **`llm:tools` + `tool:list` (host Rust)** | ✅ **SÍ** | `implementations/rust/lumen-m-light/src/host.rs` — versionado, compilado por defecto |
| **`%AGENTE.m` (bucle tool-calling)** | ❌ **NO** | `.gitignore:132` — `build-iso-i686/` entero fuera |
| **`^TOOLS` base (los 10)** | ❌ **NO** | se escribe desde `%AGENTE.m` (`D TOOLS^%AGENTE`) |
| Resto de rutinas `.m` | solo **5** en git | el taller de ISO queda fuera por diseño |

**Corrección a lo que dije antes:** el *mecanismo* está en OSS y en producción; **`%AGENTE.m` y su catálogo
`^TOOLS` no**. Están en el taller de `build-iso-i686/`, excluido a propósito (869 MB de artefactos + IPs
privadas de la red interna). Un `git clone` del repo OSS **no trae el bucle ni el catálogo**.

Es decir: **la capacidad está en la base, el agente de referencia no está publicado.** Eso es una diferencia
relevante para cualquier conclusión sobre "superficie del stack".

| | Catálogo MCP (lo que podamos en P0-1) | Catálogo MVM (`^TOOLS`) |
|---|---|---|
| Dónde vive | `TOOLS` en 4 `server.py` | global `^TOOLS(__names + desc)` |
| Quién lo lista | `tools/list` (JSON-RPC) | **`$DEVICE("tool:list")`** |
| Quién lo ejecuta | el cliente MCP | **`%AGENTE.m` → `$$EJECUTA`** |
| Coste en el prompt | **14.138 tokens, cada turno** | **0 hasta que preguntas** |
| Estado | se carga siempre | 82 → 17 tras P0-1 (pendiente) |

**Evidencia en código** (`implementations/rust/lumen-m-light/src/host.rs`):

```
$DEVICE("tool:list")          -> "nombre|descripcion" por tool
$DEVICE("tool:list","g:NS")   -> idem leyendo el catalogo de ^NS
$DEVICE("tool:list","r:RTN")  -> idem con RTN devolviendo "nombre|desc" por linea
```

Y `%AGENTE.m` es el bucle entero: pide catálogo → `llm:tools` → ejecuta las calls → devuelve resultados al LLM
→ repite hasta `MX` vueltas. **Tool-calling nativo en M, sin MCP de por medio.**

### Qué significa para P0-1

- **No invalida la propuesta.** El prompt de Hermes sigue pagando 14.138 tokens y sigue siendo el sitio donde
  más barato es recortar.
- **Acota su alcance, y eso hay que decirlo.** «117 → 52 tools» es cierto **para el cliente Hermes**. No es
  «la superficie de LUMEN son 52 tools»: la MVM tiene su propio inventario, y `^TOOLS` **no lo hemos medido**.
- **Abre una pregunta que ya está contestada:** `^TOOLS` base tiene **10 tools** (medido, ver abajo). La MVM
  no tiene el problema de superficie: lo resolvió por diseño.

---

## 2. La MVM tiene el mecanismo, pero no el catálogo cognitivo

`tools_for_profile()` + lista blanca + `$DEVICE("tool:list")` **que ya acepta una referencia**
(`"g:NS"`, `"r:RTN"`) significa que la MVM **puede** servir un catálogo distinto por perfil sin tocar el motor:
`^TOOLS` por un lado, `^TOOLS_AGENTE` por otro, y `%AGENTE` apunta al que toque.

**Pero hoy ese catálogo son 10 utilidades de nodo.** El mecanismo está; el contenido cognitivo no.
Si algún día la MVM debe hacer el trabajo de Hermes, **hay que llevarle las tools de cognición** — y entonces
P0-1 (qué 17 se cargan) se convierte en el diseño de *ese* catálogo. Hoy no es una migración: es un hueco.

**No es argumento para tocar P0-1 ahora.** Es contexto para no creer que la MVM ya resuelve esto.

---

## 3. El replay (doc `15`) cambiará el criterio de poda — pero no hoy

La tesis del `15`: el agente corre en la MVM con el LLM como **device con caché**, y cada decisión deja un
**certificado con digest** re-ejecutable.

Si eso avanza, algunas tools de thinking pierden peso:

| tool | con replay en MVM |
|---|---|
| `decision_log` | **el certificado lo sustituye** |
| `assume` | el certificado registra los supuestos |
| `state_snapshot` | **el digest** es el snapshot verificable |
| `agent_message` | igual de útil |
| `task_*` | igual de útil |

**No cambia la decisión de hoy**: el `19-que-toca-la-base` deja claro que el **contrato de caché LLM no está
definido** (*"hoy no lo hay"*), y el replay no existe. Pero conviene tenerlo escrito para la poda de dentro de
3 meses: **si el certificado llega, `decision_log` y `assume` valen menos de lo que dice el estudio del Asus.**

---

## 4. El gas es el MISMO defecto que el presupuesto 100/100

**Fuente:** `11-gas-como-mercado` §1, `22-enums-wasm-y-gas`.

El gas de la MVM es **plano**: una rama tomada (~30 µs) y una no tomada (~6 µs) cuestan **1 gas igual**. Y el
`22` encontró que **a partir de ~250 escrituras el programa se queda sin gas** con el default de 1000.

> Es literalmente `Budget exceeded: 100/100` en thinking: contador plano, default arbitrario, corta trabajo
> legítimo a mitad de tarea, falla en silencio.

**Consecuencia:** cuando arreglemos P0-4 (o el presupuesto), **el criterio debe ser el mismo en los dos sitios**
—el límite protege de bucles, no raciona trabajo interactivo; y el default no debe cortar uso legítimo—, no una
solución por servidor. Si no, arreglamos el mismo patrón dos veces con dos criterios distintos.

---

## 5. Lo que NO afecta (verificado, para no volver a mirarlo)

| Doc | Falsa alarma |
|---|---|
| `09` fábrica FHIR | sus «perfiles» son `StructureDefinition`, no catálogos de tools |
| `16` árbol / perfilador | producto y datos, no tools del agente |
| `16` nicho VistA/Cache | pide **no romper lo que funciona** — exactamente lo que hace P0-1 |
| `12` voz como `$DEVICE` | encaja «sin tocar nada»: refuerza, no condiciona |
| `02`,`04`,`05`,`13`,`14` (red, veleros, camiones, furgoneta, enjambre) | producto y hardware; no tocan el núcleo |

---

## Veredicto

| Pregunta | Respuesta |
|---|---|
| ¿P0-1 cambia? | **No.** 117 → 52 tools en el prompt de Hermes sigue siendo correcto y medible. |
| ¿Qué hay que añadir? | **Nota de alcance**: hay **dos** superficies (MCP y `^TOOLS`); P0-1 toca una. |
| ¿Qué NO adelantar? | La poda por «el certificado sustituye a `decision_log`»: el replay no existe. |
| ¿Qué se refuerza? | El gas plano y el 100/100 son **el mismo patrón**: arreglarlos con el mismo criterio. |
| ¿Qué se corrige? | `^TOOLS` **no es precedente de poda**: son 10 utilidades de nodo, ninguna cognitiva. |
| ¿Qué se descubre? | `%AGENTE.m` y `^TOOLS` **no están en OSS** (`.gitignore`); solo el *mecanismo* (`llm:tools`, `tool:list`) está publicado. |

### `^TOOLS` medido — y por qué NO es un argumento a favor de P0-1

`%AGENTE.m` línea 113 declara el catálogo base:

```
^TOOLS("__names") = "%SS,%GD,%WIFI,%NM,%CRON,%AG,sys:ps,sys:mvm,audio:info,cam:list"
```

**10 entradas.** Frente a las 117 del MCP. **Pero no son comparables, y decir «la MVM ya está podada» era
una lectura mala mía.** Mira qué son:

| tool | qué es |
|---|---|
| `%SS` | estado del sistema (proceso, RAM, red, DDP, jobs) |
| `%GD` | directorio de globals y rutinas |
| `%WIFI` | red inalámbrica |
| `%NM` | network manager |
| `%CRON` | tareas programadas |
| `%AG` | agente |
| `sys:ps`, `sys:mvm` | procesos / VM |
| `audio:info`, `cam:list` | dispositivos |

> **Son administración del nodo, no un catálogo de herramientas de agente IA.** Son el equivalente a `htop`,
> `iwconfig`, `crontab -l`. Ninguna de ellas es «leer memoria», «registrar una decisión», «buscar en la PDB»
> ni «hablar con otra sesión».

**Consecuencia:** la MVM tiene **10 utilidades de sistema**, no 10 tools cognitivas. **No aplica el principio de
P0-1 ahí**, porque no hay nada que podar: son pocas y hacen falta todas. Y **no sirve como precedente** de que
«el stack ya poda por diseño» — ese argumento se cae.

Lo que **sí** queda en pie: el *mecanismo* (`tool:list` con referencia a `^NS` o `r:RTN`) permite servir
catálogos distintos. Es una capacidad, no una política aplicada.

**Donde el `^TOOLS` sí es revelador:** con 10 utilidades de nodo y **ninguna tool cognitiva**, la MVM **no
puede** hoy ejecutar el mismo trabajo que hace Hermes con thinking+pdb. Las 117 tools del MCP no son
redundantes con `^TOOLS`: **son la capa que falta en la MVM**. Eso cambia la pregunta de sitio — no es «podemos
las dos», es «una tiene 10 utilidades de nodo y la otra 117 de cognición».

**Nada de esto bloquea P0-1.** El estudio del juego confirma la dirección y añade dos frentes futuros que
conviene dejar escritos, no resueltos.
