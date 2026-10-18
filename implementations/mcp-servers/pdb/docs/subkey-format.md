# Formato canónico de subkey numérico — DECISIÓN

**Estado:** **DECIDIDO — Opción D** (discriminante de tipo explícito)
**Fecha:** 18-oct-2026
**Evidencia:** censo read-only del nodo L13, 18-oct-2026 (29.166 filas)

---

## La decisión

> **Opción D.** Mantener `0x01` = **crudo** (motor Rust, y lo que hay en producción) y añadir `0x03` = **sortable**.
>
> Motivo: censo L13 = **26.275 num-raw / 0 sortable / 0 negativos**. D es la única opción con **coste de migración cero** que además no hipoteca el orden por bytes el día que aparezcan negativos.

---

## Los números que deciden

```
=== CONVENCIONES (parser estricto) ===
  num-raw              26275      ← 100% de los numéricos reales
  num-sortable             0
  num-ambiguous            0
  num-nonsense             0
  num-legacy-ascii        16      (PERSONALITY, formato antiguo)

=== POR NAMESPACE ===
  EMBED        {'num-raw': 25728}
  ROUTINE      {'num-raw': 492}
  QUANTUM      {'num-raw': 30}
  TRUST        {'num-raw': 25}
  PERSONALITY  {'num-legacy-ascii': 16}
```

Todos los numéricos son `ns(string).num` (posición 1). **Ningún negativo en ningún namespace.**

## Por qué NO la Opción A (que recomendaba el RFC original)

El RFC condicionaba A — sortable canónico — a que *«el censo confirme que lo dominante es sortable»*. **El censo dice lo contrario: producción es 100% cruda.**

A exigiría:
- re-encodear **26.275 filas** en producción (la operación de mayor riesgo del plan),
- tocar el **motor Rust**, que es el único lado hoy internamente consistente.

Y a cambio de nada: el criterio que hacía preferible A (orden por `memcmp` con negativos) **no está en juego hoy**, porque no hay un solo subkey numérico negativo.

## Por qué NO la Opción B (crudo canónico)

Coste de migración cero, pero **rompe el orden por bytes**: `-1.0` (`BF F0…`) quedaría *después* de `1.0` (`3F F0…`). Para arreglarlo habría que reemplazar `ORDER BY subkey` por orden sobre valor decodificado, y el `$O` del motor seguiría comparando bytes.

Hoy no se notaría — no hay negativos — pero es una mina: el día que alguien escriba `^X(-1)` con el motor, el orden se rompe en silencio. **D deja la puerta abierta; B la cierra.**

---

## El formato

```
0x01 + 8 bytes f64 big-endian CRUDO      + 0xFF     ← motor Rust, y producción
0x03 + 8 bytes f64 big-endian SORTABLE   + 0xFF     ← este módulo cuando se pide
0x01 + dígitos ASCII + 0xFF                         ← legacy (se sigue leyendo)
0x02 + UTF-8 + 0xFF                                 ← string
0x00                                                ← null sentinel
```

**El byte de tipo es el discriminante.** Un lector no adivina la convención: la lee.

| Valor | `0x01` (crudo) | `0x03` (sortable) |
|---|---|---|
| `1.0` | `3F F0 00 00 00 00 00 00` | `BF F0 00 00 00 00 00 00` |
| `-1.0` | `BF F0 00 00 00 00 00 00` | `40 0F FF FF FF FF FF FF` |

## Escritura

`SUBKEY_NUMERIC_FORMAT` (env): `raw` (default) o `sortable`.

**Default `raw`** por dos razones: es lo que el motor lee (el único lado hoy consistente) y es lo que hay en disco. Elegir `sortable` por defecto obligaría a que el motor cambiara de lector antes que el escritor.

La **lectura** siempre acepta los dos. El env solo afecta a lo que se escribe.

---

## Lo que se arregla

| Antes | Después |
|---|---|
| `^X(0)` → `nan` | `[0.0]` |
| `^X(1)` → `-3.9999999999999996` | `[1.0]` |
| `^X(2)` → `-1.9999999999999998` | `[2.0]` |
| `^X(10)` → `-0.43749999999999994` | `[10.0]` |
| `^X(-1)` → `1.0` (**signo invertido, en silencio**) | `[-1.0]` |
| `^X('a',1)` → `['a', -3.9999999999999996]` | `['a', 1.0]` |
| `encode_subkey([1])` → `01bff0…` (el motor no lo lee) | `013ff0…` (el motor sí) |

La gravedad real no era el valor deformado: era que **`pdb_get` devolvía `found:false`** sobre datos que existían en disco. Un agente concluía "ese global no existe".

---

## Migración

**Ninguna.** `0x01` sigue significando lo que ya significa en disco. Las 26.275 filas no se tocan.

Los 16 `num-legacy-ascii` de `PERSONALITY` se siguen leyendo tal cual. No hace falta normalizarlos, y si algún día se hace, es una migración aparte de 16 filas sin riesgo.

## Riesgo residual

| Riesgo | Estado |
|---|---|
| El motor sigue escribiendo `0x01` | Correcto: es lo que D declara canónico para escritura del motor |
| Alguien escribe negativos con el motor | `0x01` crudo ordena **mal** por `memcmp` con negativos. Mitigación: usar `0x03` (`SUBKEY_NUMERIC_FORMAT=sortable`) para namespaces con negativos |
| Un lector antiguo (sin `0x03`) ve un `0x03` | Lo trata como tipo desconocido. Solo afecta a quien escriba con `sortable` y lea con código viejo — no es el default |

---

## Criterios de aceptación

- [x] `test_subkey_format_canonico.py` → **PASS** (10 comprobaciones)
- [x] round-trip en ambos formatos, incluidos negativos y cero
- [x] los bytes crudos del motor se leen como `[1]`, no `[-3.9999…]`
- [x] `0.0` da `[0]`, no `nan`
- [x] pull de `0,1,2,10` → `[0, 1, 2, 10]`
- [x] nodo con valor e hijos conserva el hijo numérico
- [x] legacy ASCII sigue leyéndose
- [x] `encode_subkey([1])` emite crudo (el motor lo lee)
- [x] dentro de `0x03`, `memcmp` ordena `-10 < -1 < 0 < 1 < 10`
- [x] multinivel mixto `['ns', 5, 'key']`

## Lo que este trabajo NO decide

- El `0xFF` final duplicado (motor añade uno extra). Hoy no rompe: con un solo sub string ambos terminan igual. Puede romper con subkeys multinivel — va en commit aparte con su propio test.
- L-01 (push lento), L-03 (`seed_agentes.py`), L-05 (Poli sin rutinas). Defectos independientes.
