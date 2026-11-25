# DDP configurable — perfiles y banco de escenarios

> 2026-11-24. Implementa el requisito: **nada fijo, todo configurable, y que
> configuraciones opuestas cumplan cada una en su escenario.**
> Código ejecutable en `experimentos/ddp-modelos/`.

## Cómo ejecutarlo

```bash
cd experimentos/ddp-modelos
python perfiles.py           # los 4 perfiles, lado a lado
python banco_escenarios.py   # cada perfil contra su escenario (sale 1 si falla)
```

---

## 1 · Las cinco decisiones configurables

| Clave | Qué decide | Valores |
|---|---|---|
| `retencion_modo` | cuánto se guarda | `todo` · `ventana` · `sellado` |
| `retencion_horas` | tamaño de la ventana | número (solo si `ventana`) |
| `replicacion` | a quién se replica | `todos` · `interes` · `flota` · `hub` |
| `firma` | cómo se prueba autoría | `por_hecho` · `por_bloque` · `ninguna` |
| `compactacion` | qué se hace con lo viejo | `archivar` · `sellos` · `descartar` |
| `conflicto` | qué gana al derivar estado | `ultimo_gana` · `primero_gana` · `manual` |

## 2 · Los cuatro perfiles

| | **barco** | **enjambre** | **ledger** | **config** |
|---|---|---|---|---|
| retención | ventana 168 h | ventana 6 h | **total** | ventana 1 h |
| replicación | flota | **interes** | todos | hub |
| firma | **por_bloque 100** | por_hecho | por_hecho | **ninguna** |
| compactación | sellos | descartar | archivar | descartar |
| conflicto | último gana | último gana | **manual** | último gana |

**Cuatro políticas opuestas. Una sola implementación.** Lo único que cambia es
el diccionario.

## 3 · Resultado del banco

```
ESCENARIO 1 · BARCO — 6 h sin cobertura (21.600 muestras)
  [OK] firma por bloque, no por hecho      -> 216 firmas para 21.600 muestras
  [OK] el hub recibe todas las muestras    -> 21600 de 21600
  [OK] cadena intacta sin huecos
  [OK] compacta y conserva el sello        -> 21600 descartados, 217 bloques
  [OK] el estado sigue correcto tras compactar -> lat=41.021599

ESCENARIO 2 · ENJAMBRE — nodos efímeros
  [OK] replica lo de interés               -> 3 recibidos
  [OK] rechaza lo que no le interesa       -> rechazado por política
  [OK] firma por hecho (pocos, barato)     -> 3 firmas para 3 hechos

ESCENARIO 3 · LEDGER — inmutable
  [OK] replica todo                        -> 2 hechos
  [OK] el conflicto se DETECTA, no se resuelve -> "60"
  [OK] nada se borra nunca                 -> 3 hechos siguen

ESCENARIO 4 · CONFIG — estado puro
  [OK] el estado es el último valor        -> {'temperatura': '0.9'}
  [OK] sin firma                           -> 0 firmas
  [OK] replica al hub                      -> 2 recibidos
  [OK] descarta lo viejo sin sellar        -> 1 descartado, 0 bloques

RESULTADO: las 4 configuraciones cumplen en su escenario
```

---

## 4 · Tres fallos que solo aparecieron al ejecutar

Ninguno se habría visto leyendo el diseño. Los tres eran **fallos de concepto**,
no de código.

### Fallo 1 · La política `hub` miraba al emisor, no a mí

```python
# MAL:  return otro_nombre.startswith("HUB")
# BIEN: return self.nombre.startswith("HUB") or otro_nombre.startswith("HUB")
```
La política dice *"este nodo solo replica con el hub"*. El filtro debe mirar
**quién soy yo**, no quién envía. Estaba al revés y rechazaba todo.

### Fallo 2 · El doble gasto no se detecta por clave

Dos pagos (`pago:A->B` y `pago:A->C`) tienen **claves distintas**, así que
mirando clave por clave no hay conflicto. Pero ambos gastan el **mismo recurso**:
el saldo de A.

**Lección:** un conflicto se declara por **recurso**, no por clave. Y el recurso
se puede deducir de la clave (`pago:A->B` → `saldo:A`), sin que el usuario tenga
que declararlo. Implementado así.

### Fallo 3 · La compactación se comía el estado actual

Al compactar, el barco descartó **21.600 hechos de 21.600** y el estado quedó
vacío. Es el error clásico: **no se puede tirar el último hecho de una serie**
sin perder el presente.

**Regla adoptada:** la compactación archiva historia; **el último hecho de cada
serie se conserva siempre**. Implementado y verificado.

---

## 5 · Lo que esto demuestra

El requisito era *"que diferentes configuraciones vayan bien y cumplan para los
diferentes escenarios"*. El banco lo comprueba con criterios explícitos, no con
"no ha petado":

- El barco **prueba completitud** (21.600 de 21.600, cadena intacta).
- El enjambre **filtra** y firma cada hecho.
- El ledger **no borra** y **detecta** el conflicto en vez de resolverlo.
- El config **prescinde de la historia** y no firma nada.

Si alguna de esas políticas se rompiera, el banco sale con código 1.

## 6 · Lo que todavía NO está resuelto

- **El perfil no es aún un fichero de configuración real.** Hoy es un
  diccionario en Python. Falta cómo se declara (¿`^SYS("DDP","PERFIL")`?, ¿JSON?)
  y cómo se cambia en caliente.
- **La firma está simulada** (hash, no Ed25519 real). El PKI real ya existe en
  `lumen-nodo/identidad.rs`; falta conectarlo.
- **La replicación es en memoria.** No hay transporte: falta usar `lumen-znet`.
- **No hay prueba de carga** con las 4 configuraciones a la vez.
- **Falta el escenario de partición** (split-brain) que señaló Poli.

## 7 · Siguiente paso propuesto

Llevar **un** perfil (el de barco, que es el más exigente) a código real:
fichero de configuración, firma Ed25519 de verdad y transporte por `lumen-znet`.
Los otros tres perfiles ya están probados en el prototipo y solo tendrían que
cambiar el diccionario.
