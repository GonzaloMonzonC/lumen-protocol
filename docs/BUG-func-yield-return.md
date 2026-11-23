# RESUELTO — una `$$FUNC` que cede perdía su valor de retorno

> Detectado y cerrado el 23-nov-2026 depurando Smith.
> Commit: `27c330f8` en `lumen-protocol`.

## Síntoma

Una función M que hace una llamada a un device que produce `yield`
(`llm:call`, `user:ask`) y luego devuelve un valor con `QUIT`, **perdía ese
valor** cuando el motor reanudaba.

```m
A1(n)              ; sin ceder -> funcionaba
 QUIT n
     W $$A1^T(7)   ->  7        ✅

A2(n)              ; cedía en llm:call -> NO funcionaba
 NEW r
 SET r=$DEVICE("llm:call","hola","sys","local","m")
 QUIT 1
     W $$A2^T(1)   ->  ""       ❌ (debería ser 1)
```

Fallaba **en silencio**: sin error, sin excepción, valor vacío. El peor modo.

## Por qué se rompía — dos causas encadenadas

El primer intento de arreglo se quedó a medias porque el fallo tenía dos
capas, y la segunda no se veía hasta quitar la primera.

### Capa 1 — el bucle infinito del `yield_future`

`reanudar_funcion` hacía `yield_future = None` al reanudar, con la idea de que
"el device ya se resolvió". Pero `$DEVICE("llm:call")` es **re-ejecutable por
diseño**: si encuentra un id en `yield_future`, reutiliza ese future y hace
`poll` en vez de crear otro fork.

Al borrar el id, la instrucción `SET r=$DEVICE(...)` re-ejecutada creaba una
llamada al LLM **nueva**, que volvía a ceder, que volvía a reanudar… Traza
real del bucle:

```
[REANUDAR] entrada inner_ip=4 recogido=false
[REANUDAR]   i=4 op=Set ctrl=Continue yield=true
[REANUDAR] entrada inner_ip=4 recogido=false      ← y otra vez, 60+ veces
```

`inner_ip` clavado en el `SET` para siempre. El id **no debe borrarse**: lo
limpia el propio device cuando `llm_poll` devuelve `Some`.

### Capa 2 — el valor viajaba en un registro efímero

Quitada la capa 1, la función ya llegaba al `QUIT`. Pero el valor seguía
perdiéndose, y la razón es de diseño:

- El valor del `QUIT` viajaba en `return_value`, un registro **único y
  efímero**.
- La instrucción del principal (`W "|",$$A2^T(1),"|"`) ya se había ejecutado
  con el `Null` que devolvió `eval_function` al ceder.
- Ese `Null` ya estaba impreso. Cuando el valor real llegaba, **no tenía
  dónde ir**: la instrucción ya se había consumido.

## El arreglo — el mismo mecanismo por el que ya funcionaba `.REF`

La clave conceptual: **`.REF` funciona porque escribe en `state.vars`, que
sobrevive al yield**. El `$$FUNC` no tenía ese sitio. Había que dárselo, no
arreglar "el viaje" del valor.

1. **El `QUIT` del resume deposita el valor en `state.vars`**, con clave
   `%QUITFUNC:LABEL.RUT#depth` (label + rutina + profundidad, para no
   colisionar con `$$FUNC` anidadas).
2. **Se rebobina el ip del principal** y se re-evalúa la expresión.
3. **`eval_function` recoge el valor** de `state.vars` y lo devuelve, **sin
   re-entrar en la función** (re-entrar dispararía un segundo `llm:call`).
4. **Al rebobinar se trunca `state.output`** a lo que había antes de la
   instrucción. Sin esto el WRITE parcial de cada intento se acumulaba:
   `"|||1|"` en vez de `"|1|"`.

Ese último punto costó verlo y es imprescindible: el rebobinado re-ejecuta la
instrucción entera, incluido su `WRITE`.

## Verificación (salida real)

```
A1 sin ceder     '|7|'          control
A2 cede, QUIT 1  '|1|'          antes: ''
A3 cede, QUIT r  '|OP:sys|'     antes: ''
```

Smith de punta a punta, con `^LLMROUTER(mode)="local^m"` apuntando al mock:

```
$$STREAM^SMITH  ->  '|RET=1|OUT_LEN=223|'
```

Las **dos** vías a la vez: valor de retorno (`RET=1`) y `.REF` con 223
caracteres de texto de los asesores.

Tests: **80/80** (79 previos + `funcion_que_cede_devuelve_su_valor_de_retorno`).
Verdes los que protegen el camino que no debía cambiar:

- `yield_inside_local_do_resumes_no_replay`
- `yield_inside_do_block_no_duplicate_effects`
- `yield_inside_for_body_no_duplicate_effects`
- `nested_for_with_device_resumes_without_collision`

## Lo descartado por el camino (con pruebas, no suposiciones)

| Hipótesis | Resultado |
|---|---|
| El `QUIT` con valor no se compila bien | **No.** `vm.rs` evalúa el argumento y pone `return_value` |
| La función no llega al `QUIT` | **No.** Un `WRITE` antes del `QUIT` sí se imprime |
| `.REF` está roto | **No.** Es el canal que siempre funcionó |
| El valor se pierde en `reanudar_funcion` | **Parcial.** Ahí estaba la capa 1; la capa 2 era anterior |
| Rebobinar el ip basta | **No.** Hay que truncar `state.output` y depositar el valor en `state.vars` |

## Reproducir

```bash
# Caso mínimo (necesita el mock en 127.0.0.1:58099)
python ~/AppData/Local/hermes/scripts/diag_quit_yield.py

# Pipeline completo de Smith
python ~/AppData/Local/hermes/scripts/smith_e2e2.py
```

Traza del motor:

```bash
LUMEN_TRACE_FUNC=1 python diag_quit_yield.py
```

## Lección de método

El arreglo salió de una observación de Gonzalo: *"el paso por referencia
funciona, ahora usamos `D FUNC^RUTINA(.variable)`"*.

No porque hubiera que usar `.REF` en Smith, sino porque el `.REF` funciona
**porque escribe en un sitio que sobrevive**. Eso es lo que había que copiar
al retorno. Se estaba intentando arreglar el viaje del valor cuando el
problema era el destino.
