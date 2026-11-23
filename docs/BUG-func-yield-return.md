# BUG ABIERTO — una `$$FUNC` que cede pierde su valor de retorno

> Detectado el 23-nov-2026 depurando Smith. **No resuelto.**
> Caso mínimo reproducible al final. Empezar por ahí.

## Síntoma

Una función M que hace una llamada a un device que produce `yield`
(`llm:call`, `user:ask`) y luego devuelve un valor con `QUIT`, **pierde ese
valor** cuando el motor reanuda.

```m
A1(n)              ; sin ceder -> funciona
 QUIT n
     W $$A1^T(7)   ->  7        ✅

A2(n)              ; cede en llm:call -> NO funciona
 NEW r
 SET r=$DEVICE("llm:call","hola","sys","local","m")
 QUIT 1
     W $$A2^T(1)   ->  ""       ❌ (debería ser 1)

A3(n)              ; cede y devuelve el propio texto
 NEW r
 SET r=$DEVICE("llm:call","hola","sys","local","m")
 QUIT r
     W $$A3^T(1)   ->  ""       ❌
```

## Lo que está descartado (con pruebas, no suposiciones)

| Hipótesis | Resultado |
|---|---|
| El `QUIT` con valor no se compila bien | **No.** `vm.rs:913` evalúa el argumento y pone `return_value = Some(value)` |
| La función no llega al `QUIT` | **No.** Con un `WRITE "[llego]"` antes del `QUIT`, el texto SE IMPRIME: la función termina |
| `.REF` está roto | **No.** `S OK=$$FUN(args,.RES)` rellena RES correctamente aunque la función ceda |
| El valor se pierde en `reanudar_funcion` | **Probable.** Ahí está el candidato, pero el motor no siempre pasa por ahí al reanudar |

## Dónde mirar

`implementations/rust/lumen-m-light/src/vm.rs`:

- **`vm.rs:494`** — `while (!func_frames.is_empty() ...)`: el bucle de
  reanudación de funciones en `run_slice`.
- **`vm.rs:520`** — `match self.reanudar_funcion(&fr)`: si devuelve `Ok(v)`,
  hace `self.return_value = Some(v)` y `continue`.
- **`vm.rs:585-602`** — limpieza de `yield_requested`. **Ojo**: solo se limpia
  si `!en_funcion`. Dentro de una función queda activo a propósito, para que
  `eval_function` sepa que el device se resolvió.
- **`vm.rs:780-800`** — el bucle de `reanudar_funcion`. Comprueba
  `yield_requested` en CADA instrucción y sale con `Err(())` si sigue activo.

La sospecha principal: al reanudar dentro de una función, `yield_requested`
sigue en `true` (por el `if !en_funcion`), así que el bucle de
`reanudar_funcion` sale antes de llegar al `QUIT`. Se intentó limpiarlo al
entrar en el bucle y **no bastó** — señal de que el motor reanuda por otro
camino, o de que el frame que llega no es el esperado.

## Cómo reproducir

Script listo: `~/AppData/Local/hermes/scripts/diag_quit_yield.py`

```python
import os, sys, time
os.environ['LUMEN_MLIGHT_LIB'] = '.../target-sqltest/release/lumen_mlight.dll'
sys.path.insert(0, '.../implementations/mcp-servers/pdb')
import lumen_mlight as L

RUT = {'T': 'A2(n)\n NEW r\n SET r=$DEVICE("llm:call","hola","sys","local","m")\n QUIT 1\n'}
# ejecutar `W "|",$$A2^T(1),"|"` con bucle de resume hasta que deje de ceder
```

Necesita un servidor LLM en `127.0.0.1:58099` o cualquier mock que responda.
Hay uno persistente en `~/AppData/Local/hermes/scripts/mock_llm.py`.

Con traza del motor:

```bash
LUMEN_TRACE_FUNC=1 python diag_quit_yield.py
# [FUNC] PUSH A2@T inner_ip=2 pila=1
# [RUNSLICE] reanudando A2 ip=2      <- reanuda y no avanza al QUIT
```

## Impacto

- **No afecta al canal `.REF`**, que es el que usa el pipeline de Smith.
- **Sí afecta** a cualquier `S = $$FUNC(...)` donde FUNC llame a un LLM.
  El valor llega vacío sin error, que es lo peor: falla en silencio.
- Workaround conocido: usar un parámetro `.REF` en vez del valor de retorno.

## Cómo se manifestó en Smith

`SINTETIZA^SMITH(msg,doms,res,OUT)` cede en su `llm:call` y escribe el
resultado en `OUT` (`.ref`). Al llamarla con `$$`, el valor de retorno se
pierde — pero a `OUT` **sí llega**. Verificado:

```
LANZATODOS + RECOGE  ->  ids=[1,2], 416 caracteres de asesores   OK
SINTETIZA por .REF   ->  OUT tiene el texto                      OK
SINTETIZA por $$     ->  "" (valor de retorno)                   FALLA
```

Así que el pipeline puede completarse usando `.REF` en los tres pasos. Lo que
queda por comprobar es por qué `STREAM` no propaga su `RES` al llamador
después de ese último yield.

## Pista para la próxima sesión

Antes de tocar `vm.rs`, comprobar con traza **si `reanudar_funcion` llega a
ejecutarse** cuando `SINTETIZA` cede. Si no se ejecuta, el valor se pierde en
`eval_function` (el camino de `vm.rs:3188`), no en `reanudar_funcion`.

Añadir temporalmente un `eprintln!` en las dos entradas y ver cuál se imprime.
