# Certificado de decisión (replay verificable)

Implementa el ciclo completo del producto "caja negra de agentes" (doc `15` del
estudio): emitir un certificado de decisión, re-ejecutarla y demostrar que da
lo mismo.

---

## Un certificado necesita CUATRO piezas, no una

El digest canónico del estado (`determinismo-replay.md`) solo cubre la primera.
Un replay completo necesita:

| pieza | de dónde sale |
|---|---|
| 1. estado resultante | `digest_canonico.digest_de_globals` |
| 2. versión de reglas | `^REGLA(ns, *)` → `digest_de_reglas` |
| 3. versión de modelo | campo `modelo` del certificado |
| 4. respuestas LLM | `^LLMCACHE(clave)` con texto exacto |

Sin las cuatro, el replay no demuestra nada: si el LLM devuelve otro texto, la
decisión cambia y no hay forma de saber si fue el modelo o la lógica.

---

## Uso

```python
from certificado import grabar_reglas, emitir, verificar, clave_llm, grabar_llm

# 1. reglas versionadas
d_reglas = grabar_reglas(pdb, "credito", {"max_deuda": 10000, "umbral": 0.4})

# 2. caché LLM con clave estable
clave = clave_llm("modelo-a", "evalua esta solicitud", {"temp": 0})
grabar_llm(pdb, clave, {"texto": "..."})

# 3. emitir
r = L.execute_sqlite(PROGRAMA)
cert = emitir("credito", PROGRAMA, r, d_reglas,
              [{"clave": clave, "modelo": "modelo-a", "texto": "..."}],
              modelo="modelo-a")

# 4. verificar (devuelve informe, no booleano)
informe = verificar(cert, L.execute_sqlite(PROGRAMA), d_reglas_actual)
# -> ok | estado_distinto | reglas_cambiadas | firma_invalida
```

### Por qué `verificar` devuelve cuatro veredictos

Cada uno significa algo distinto y el cliente necesita distinguirlos:

| veredicto | qué significa |
|---|---|
| `ok` | la decisión se reproduce exactamente |
| `estado_distinto` | la decisión cambió (mira `diff_politicas`) |
| `reglas_cambiada`s | el certificado es válido pero ya no aplica la misma política |
| `firma_invalida` | alguien tocó el certificado |

Un booleano colapsaría estos cuatro casos en "no", que no es información útil.

---

## La clave de caché LLM

```
sha256(modelo + prompt + params)
```

Incluye **todo** lo que puede cambiar la respuesta. Si cambia el modelo, la
clave cambia, el replay no encuentra la respuesta vieja — y **eso es lo
correcto**: un certificado que se validara con otro modelo estaría mintiendo.

---

# TRES BUGS ENCONTRADOS AL CONSTRUIR ESTO

Los tres son de la misma familia: **algo que devuelve un resultado plausible
sin haber hecho el trabajo**. Documentarlos vale más que el certificado.

## Bug 1 — `I cond` + bloque SIN `D` ejecuta el cuerpo SIEMPRE

**Este es el grave, y afecta al estudio del juego.**

En M, un `I` con bloque indentado **necesita el `D`**:

```mumps
; MAL — ejecuta el S aunque la condición sea falsa
I x>5
. S y=99

; BIEN
I x>5 D
. S y=99
```

Medido:

| forma | condición falsa | condición cierta |
|---|---|---|
| `I x>5` (sin D) | `y=99` ❌ | `y=99` ✓ |
| `I x>5 D` | `y=0` ✓ | `y=99` ✓ |

Sin `D`, **todas las ramas se ejecutan siempre**. No es un fallo de rendimiento:
es de corrección, y silencioso (el programa "funciona" y da un número).

**Consecuencia para el estudio del juego:** `bench_blockform.py` tiene **54
bloques sin `D`**. Todo el "hallazgo del 6×" y los 2,05 ms/tick se midieron
sobre un tick cuya lógica de ramas era incorrecta. El número de rendimiento
puede ser válido (se ejecutaba más trabajo, no menos), pero **el resultado de la
simulación no era el que decía**. Ver la corrección en el estudio.

## Bug 2 — `L.execute()` no lee la PDB

```python
L.execute(prog)          # globals vacías: la decisión sale siempre igual
L.execute_sqlite(prog)   # hace snapshot de los namespaces y persiste el diff
```

`execute()` es la VM pura: recibe `globals_=` explícitas o nada. Con un programa
que lee `^REGLA` y `^SOLICITUD`, devuelve vacío y la decisión sale constante.
**Parece "las reglas no cambian nada"** en vez de "no estoy leyendo la base".

## Bug 3 — `tool_order` devuelve UNA clave en `value`, no una lista en `keys`

```python
r = pdb.tool_order({"ns": "REGLA", "subs": [ns, ""], "direction": 1})
# r = {'success': True, 'value': 'max_deuda'}   <- una sola, no r['keys']
```

Para recorrer un namespace hay que iterar pasando el último subkey como punto
de partida. La primera versión de `leer_reglas` leía `r.get("keys")`, recibía
`None`, y devolvía `{}` **en silencio**: el digest de reglas salía siempre igual
y el replay decía "reglas cambiadas" cuando no había cambiado nada.

---

## Los tests

```bash
LUMEN_REPO=~/Documents/GitHub/lumen-protocol python test_certificado.py
```

Cinco comprobaciones sobre una decisión de crédito real:

1. emitir + replay → `ok`
2. cambiar el umbral 0.4→0.9 → la decisión cambia (0→1) y el replay lo detecta
3. cambiar el modelo → la clave de caché cambia, la respuesta ya no aparece
4. manipular el certificado → `firma_invalida`
5. contrafactual → detecta que la decisión habría cambiado

Verificado que **discrimina**: con umbral 0.4 deniega y con 0.9 concede. Si
diera igual, el test no probaría nada.

---

## Lo que esto NO resuelve

- **No hay `^REGLA` en producción todavía.** `grabar_reglas` la crea; ninguna
  decisión real la usa aún.
- **No hay caché LLM en producción.** `llave_llm`/`grabar_llm` existen; el
  device `llm:call` del motor **no consulta la caché** — habría que conectarlo.
- **No hay almacén de certificados.** `^CERT(id)` está propuesto, no implementado.
- **No hay replay masivo.** El "diff de políticas" del doc 15 sobre 10.000
  decisiones necesita ejecutar 10.000 replays; aquí está la pieza unitaria.
- **La firma es sha256, no criptográfica.** Detecta manipulación accidental, no
  a un adversario que recalcule el hash. Para eso hace falta clave privada.
