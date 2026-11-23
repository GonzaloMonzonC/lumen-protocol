# Estado de la sesión 22-23 nov 2026

> Traspaso para retomar en frío. Lo hecho, lo verificado y lo que queda.

## Hecho y verificado en producción

| Qué | Dónde |
|---|---|
| **Smith**: asesores vuelven a lanzarse (doble escape en Python y en M) | `poli` |
| **`entries_for_fiber`**: el fiber ve la PDB del turno | `lumen-m-light/src/host.rs` |
| **`DEVICE_CATALOG`** declaraba mal `audio/img/cam` | `host.rs` |
| **`hw:temp`** cae a `/sys/class/hwmon` + 11 tests | `hw.rs` |
| **`sys:mvm`** paniqueaba en WASM | `host.rs` |
| **`m_execute_async`**: el bucle ceder/inject/reanudar vive en el motor | `wasm.rs` |
| **Estado observable de Smith** (`^SMITHID`: fase, dominios, asesores, ms) | `poli` |
| **Tres `SET OUT=""`** que rompían parámetros `.ref` | `poli` |
| **Web**: `/agents`, bilingüe, menos venta | `lumen-site` |
| **LLM de pruebas**: cascada de 11 modelos `:free`, 1500 tokens, rate limit por minuto | `lumen-site/functions` |

**79/79 tests Rust verdes.**

## Segunda tanda (23-nov, tarde)

| Qué | Dónde |
|---|---|
| **BUG `$$FUNC` que cede pierde su retorno — CERRADO** | `lumen-m-light/src/vm.rs` (`27c330f8`) |
| **Smith de punta a punta**: `RET=1` + 223 caracteres por `.REF` | verificado |
| Regresión nueva: `funcion_que_cede_devuelve_su_valor_de_retorno` | `vm.rs` |

**80/80 tests Rust verdes.**

El bug del intérprete que bloqueaba Smith está resuelto. Resumen de la causa:
`reanudar_funcion` borraba `yield_future` (y `$DEVICE("llm:call")` es
re-ejecutable por diseño → fork nuevo en cada resume, bucle infinito), y el
valor del `QUIT` viajaba en `return_value`, un registro efímero que ya se
había consumido. Ahora el valor se deposita en `state.vars`
(`%QUITFUNC:LABEL.RUT#depth`) —el mismo mecanismo que hace funcionar `.REF`—
y se recoge al re-evaluar la expresión.

Detalle completo en `docs/BUG-func-yield-return.md`.

## Limpieza hecha

- Borrado `lumen-protocol-web` (repo + proyecto Cloudflare): duplicaba la demo.
- Borrado `lumen-agents`: era la tercera copia de las rutinas. Rescatado su
  `seed/personas.mac` y dos docs → `poli/seed/` y `poli/docs/`.
- Borrado `orchestrator.m`: no compilaba como etiqueta y nadie lo usaba.
- Borrados 1,4 MB de wasm duplicado en `lumen-site/site/demo/`.

**Ahora hay UNA sola copia de `SMITH.mac`** (`poli/src/core/`). Antes había
dos con contenido distinto, y los fixes se hacían en la que no se ejecutaba.

## Lo que queda abierto

### 1. BUG del intérprete — RESUELTO (23-nov, tarde)
`docs/BUG-func-yield-return.md`

Cerrado en `27c330f8`. Una `$$FUNC` que cede conserva ahora su valor de
retorno. Afectaba a cualquier `S = $$FUNC()` con LLM dentro y fallaba en
silencio.

### 2. Smith de punta a punta — RESUELTO
Verificado: `$$STREAM^SMITH` devuelve `RET=1` **y** llena `.REF` con 223
caracteres de los asesores. Las dos vías funcionan a la vez.

**Nota sobre credenciales**: `llm_router.mac` elige `deepseek` por defecto.
Sin `DEEPSEEK_API_KEY` el pipeline devuelve un `401` de `api.deepseek.com`
—correctamente, dentro de `OUT`, sin romper—. Para pruebas con mock:
`S ^LLMROUTER("fast")="local^m"` (y lo mismo para `balanced` y `deep`).

### 3. Fibers en WASM — EN GRAN PARTE RESUELTO, SIN RAYON

No hay hilos: `fiber:bg` da error limpio porque el pool usa
`std::thread::spawn` + `mpsc`, que no existen en wasm32.

**Pero Smith ya no los necesita.** Se descubrió que `llm:fork` y `llm:await`
SÍ funcionan en el navegador, y que basta con sustituir `$FIBER("bg")` por
ese par para tener el pipeline completo. Medido en el WASM real:

```
llm:fork  -> id (encola, no bloquea)
llm:await -> texto (o vacío hasta que el host inyecte)
ciclo completo con m_execute_async: RET=1 | FASE=hecho | N=2 | RESP=2
```

Consecuencia: **`wasm-bindgen-rayon` deja de ser necesario para Smith**. Solo
haría falta para correr M arbitrario en paralelo en el edge — no para LLM.
La vía de `COOP`/`COEP` y el rediseño async de `vm.rs` quedan aparcados
hasta que aparezca ese caso.

Diferencia práctica entre los dos caminos:
- **nodo (fibers)**: paralelismo real, N llamadas HTTP a la vez.
- **navegador (fork)**: concurrencia, el host las resuelve entre pasadas.

### 4. IndexedDB
Valorado: **no va en el motor** (IndexedDB no tiene API síncrona y `$SET` sí).
Va en el consumidor: guardar el array `globals` que ya devuelve cada ejecución.

**Ojo al probar en WASM**: `m_execute_routines_out` NO persiste globals entre
llamadas. Hay que pasar `r.globals` de una a la siguiente, como hace la
consola con su variable `globals`. Si no, cada ejecución arranca con la PDB
vacía y los síntomas engañan (un seed que "no funciona", un `DETECT` que
siempre devuelve `poli`).

### 5. Ejemplo de flujo de acceso
Diseñado, sin construir: código de acceso → PDB → registro → LLM detecta
patrón → escribe regla → se aplica en caliente. **Sin HTTP y sin visión
facial** (descartadas por RGPD y por no caber en el binario).

### 6. Consola: pintar el estado de Smith en vivo
`^SMITHID` ya publica todo lo necesario — `fase`, `dominios`, `n`, `resp`,
`fallidos`, `timeouts`, `ms`, `res` y la traza `hist`. La consola todavía no
lo lee. **Media hora de trabajo y es lo que más se ve en la demo.**

## Smith: orquestación (23-nov, noche)

Tras el bug del intérprete, se revisó la orquestación entera y se reescribió
lo que estaba mal. Cuatro commits en `poli` (`8e84e20` → `e05b70e`) más uno
en `lumen-protocol` (`5f9839f1`).

### Lo que se arregló

| Problema | Estado |
|---|---|
| `DEVICE_CATALOG` no listaba `fiber:*` | el device funcionaba pero `sys:has` daba 0 **también en el nodo**; Smith tomaba el camino de navegador en el nodo y acababa en `stack overflow` |
| `wasm_llm_fork` deduplicaba contra una lista que se vacía (`mem::take`) | 3 forks del mismo prompt daban `1,2,3`; ahora `1,1,1` |
| `llm:await` que cede revienta el motor wasm | en wasm no cede; el host completa los forks |
| `m_execute_async` solo reanudaba | ahora repite si completó con forks en vuelo |
| Tres listas de agentes desincronizadas | `SMITHKW` lee la PDB: `KW`, `LABEL` y `MODES` |
| `ACTIVE()` preguntaba por `smith:stream`, que Smith no usa | ahora por `llm:fork` |
| Cabecera documentaba una arquitectura fantasma | reescrita |
| Timeout único de 120 s por asesor | dos niveles: `timeout_ms` (90 s) y `deadline_ms` (150 s) |
| Un timeout y un error eran indistinguibles | `JUNTA` lee el campo `ok`; `^SMITHID("fallidos")` |
| Tope de 3 dominios invisible | `max_dominios` configurable, con aviso si se sube |
| Sin revisión del resultado | fase `revisando` + `max_rehacer` |

### Máquina de fases (patrón tomado de Lisa)

`STREAM` ya no es una función monolítica: es un bucle sobre `PASO^SMITH`, que
avanza **una** fase y vuelve. Fases:

```
recibido -> detectando -> lanzando -> esperando -> sintetizando -> revisando
                                                                      |
                                                          hecho / fallido (1 rehacer)
```

`vacio` es terminal (sin asesores). Cada transición queda en
`^SMITHID("hist",n)` con formato `desde|hasta|motivo|hora`, así que se puede
reconstruir por dónde pasó, no solo dónde está.

Lo que **no** se copió de Lisa: sus 8 estados (`PLANNING`, `BLOCKED`,
`REVIEWING` con feedback iterativo). Smith no planifica pasos ni los ejecuta;
reparte una consulta. Meter ese vocabulario sería disfrazar de progreso algo
que no lo es.

### Configuración nueva en `^SMITH`

| Global | Defecto | Qué hace |
|---|---|---|
| `^SMITH("regla","max_dominios")` | 3 | tope de asesores por consulta |
| `^SMITH("regla","timeout_ms")` | 90000 | timeout **por asesor** |
| `^SMITH("regla","deadline_ms")` | 150000 | tope del pipeline entero |
| `^SMITH("regla","max_rehacer")` | 1 | reintentos de la síntesis en `revisando` |

**Ojo con `timeout_ms`:** `fiber:await_all` lo aplica a CADA asesor, no al
lote. 3 asesores a 90 s son hasta 270 s. Por eso existe `deadline_ms`, que es
el que acota de verdad.

## Decisiones tomadas (no reabrir)

- **`lumen.cadences.app` ES la página oficial de lumen-protocol.** El
  subdominio `lumen-protocol.cadences.app` queda en standby: el SEO ya apunta
  a `lumen.cadences.app`.
- **Frontera LUMEN/ECOS: se queda como está.** No se redefine qué se libera.
- **Idioma: inglés y español, todo traducido.** En `lumen-site` el defecto es
  español (público hispanohablante); en un sitio del protocolo sería inglés.
- **La web usa `lumen-site`**, no un repo nuevo. No crear más repos de web.

## Trampas conocidas de M-Light

En `skills/lumen/mvm-interpreter-pitfalls`, que es la fuente viva. Resumen de
las caras, todas con caso mínimo reproducible:

- `FOR` que duplica iteraciones si el cuerpo llama a ciertas cosas (crear
  fibers, ceder, `DEVICE` dentro).
- `QUIT` sin valor devuelve vacío — **es correcto**.
- `SET .ref = "literal"` rompe la referencia.
- **NO borrar `yield_future` al reanudar.** `$DEVICE("llm:call")` es
  re-ejecutable por diseño: reutiliza el id para hacer `poll`. Borrarlo
  dispara un LLM nuevo en cada resume (bucle infinito).
- **Rebobinar el ip para re-evaluar una expresión exige truncar
  `state.output`** a su longitud previa, o el `WRITE` de cada intento se
  acumula.
- **`IF cond GOTO ETIQUETA` NO SALTA — la condición se ignora.** Verificado
  con caso mínimo: imprime la línea siguiente tanto si la condición es cierta
  como si no. Para despachar por estado, encadena `IF ... QUIT 1` y
  `QUIT $$SIGUIENTE^RUTINA(args)`. Y ojo: una llamada a rutina **no comparte
  locales**.
- **`GOTO` a etiqueta en una rutina que luego cede** pierde el resultado y en
  WASM acaba en `unreachable`.
- **`.ref` de dos saltos no propaga**: `DO OTRA(ids,.OUT)` deja `OUT` vacío;
  hace falta una variable local intermedia.
- **Varios `llm:await` en UNA línea** revientan el motor wasm con 2+ ids.
  Uno por línea.
- **`DO` con cuerpo de puntos** duplica efectos cuando la rutina cede.
- `$GLOBAL` no existe.
- **`m_llm_pending()` hace `mem::take`**: vacía la lista al leerla. Cualquier
  deduplicación que dependa de ella se rompe en cuanto el host la consulta.
- **En WASM, `m_execute_routines_out` no persiste globals**: hay que pasar
  `r.globals` entre llamadas o cada ejecución arranca con la PDB vacía.
- Probar fibers con mock **persistente**, no embebido.
