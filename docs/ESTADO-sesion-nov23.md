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

### 3. Fibers en WASM
No hay hilos. `fiber:bg` da error limpio. Tres caminos valorados:
`wasm-bindgen-rayon` (necesita COOP/COEP), async real del VM (rediseño), o
dejarlo secuencial y decirlo. **Ninguno empezado.**

### 4. IndexedDB
Valorado: **no va en el motor** (IndexedDB no tiene API síncrona y `$SET` sí).
Va en el consumidor: guardar el array `globals` que ya devuelve cada ejecución.

### 5. Ejemplo de flujo de acceso
Diseñado, sin construir: código de acceso → PDB → registro → LLM detecta
patrón → escribe regla → se aplica en caliente. **Sin HTTP y sin visión
facial** (descartadas por RGPD y por no caber en el binario).

## Decisiones tomadas (no reabrir)

- **`lumen.cadences.app` ES la página oficial de lumen-protocol.** El
  subdominio `lumen-protocol.cadences.app` queda en standby: el SEO ya apunta
  a `lumen.cadences.app`.
- **Frontera LUMEN/ECOS: se queda como está.** No se redefine qué se libera.
- **Idioma: inglés y español, todo traducido.** En `lumen-site` el defecto es
  español (público hispanohablante); en un sitio del protocolo sería inglés.
- **La web usa `lumen-site`**, no un repo nuevo. No crear más repos de web.

## Trampas conocidas de M-Light

En `skills/lumen/mvm-interpreter-pitfalls`:

- `FOR` que duplica iteraciones si el cuerpo llama a ciertas cosas.
- `QUIT` sin valor devuelve vacío — **es correcto**.
- `SET .ref = "literal"` rompe la referencia (el bug de hoy).
- **NO borrar `yield_future` al reanudar.** `$DEVICE("llm:call")` es
  re-ejecutable por diseño: reutiliza el id para hacer `poll`. Borrarlo
  dispara un LLM nuevo en cada resume (bucle infinito).
- **Rebobinar el ip para re-evaluar una expresión exige truncar
  `state.output`** a su longitud previa, o el `WRITE` de cada intento se
  acumula.
- `$GLOBAL` no existe.
- Probar fibers con mock **persistente**, no embebido.
