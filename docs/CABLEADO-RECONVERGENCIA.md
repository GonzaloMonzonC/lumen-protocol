# Cableado — las cuatro piezas ahora se llaman

> 2026-11-26. Cierra el diseño de reconvergencia: las piezas estaban probadas por
> separado, pero no conectadas.

---

## 1 · Qué faltaba

| Pieza | Probada | ¿Se usaba? |
|---|:---:|---|
| Tipado de hechos | ✅ | sí, al crear hechos nuevos |
| Digest recalculable | ✅ | **solo en tests** |
| Hecho de conflicto | ✅ | **no, nadie lo emitía** |
| Cota de epoch | ✅ | **no, nadie la comprobaba** |

**Tres de cuatro piezas estaban en el cajón.** Es el patrón clásico: código
correcto que nunca se ejecuta en producción.

## 2 · Lo que se conectó

### Cota en la recepción

`recibir_hechos_con_cota(...)` comprueba el epoch **antes de guardar**:

```rust
if let Some(cota) = cota {
    let veredicto = cota.revisar(epoch_previo, h.epoch);
    if veredicto.va_a_cuarentena() {
        r.en_cuarentena += 1;
        r.cuarentena.push((h.instance_id.clone(), veredicto.motivo()));
        continue;   // NO se guarda
    }
}
```

**Antes de guardar, no después:** un hecho con epoch imposible que llegue al store
ya no se puede desalojar sin violar "nunca se borra".

### Conflictos persistidos

`persistir_conflictos(...)` convierte el `Vec<Conflicto>` del resumen en hechos
firmados en la serie `conflictos`, encadenados como cualquier otra serie.

**Era el agujero:** el resumen es memoria; al reiniciar, los conflictos
desaparecían.

`ResumenRecepcion` gana dos campos:

```rust
pub en_cuarentena: usize,
pub cuarentena: Vec<(String, String)>,   // (instancia, motivo)
```

## 3 · Los tres bugs que aparecieron al cablear

Y esto confirma el patrón: **los bugs salen al juntar, no al construir.**

### Bug 1 — `aceptados=1` pero `guardados=0`

El test decía que el hecho se aceptaba... y el store estaba vacío. **El peor tipo
de bug:** reporta éxito y no guarda nada.

**Era del test, no del código:** `contar_serie` busca en la rama principal
(instancia `""`), y el hecho iba en `inst-A`. El hecho **sí** estaba guardado.

Lección: `contar_serie` y `leer_serie_de_rama` no miran lo mismo. Confundirlos
da un falso negativo que parece un bug de escritura.

### Bug 2 — todo conflicto salía como `decision-seguridad`

En `persistir_conflictos` se pasaba el tipo **fijo**:

```rust
let tipo = TipoHecho::ConRevision;   // ← SIEMPRE
let motivo = motivo_de(c, tipo);
```

Así que **una reserva de recurso disputada se clasificaba como decisión de
seguridad**. Consecuencia real: lo urgente va a la cola lenta, y el operador mira
lo que no toca primero.

**Arreglo:** `Conflicto` ahora lleva el `tipo` del hecho que chocó, y se usa el
real.

```
antes:  DRON-1:reserva:0 -> motivo Some(DecisionDeSeguridad)
ahora:  DRON-1:reserva:0 -> motivo Some(RecursoDisputado)
```

### Bug 3 — `Conflicto` sin el campo tipo en 4 sitios

Los tests y el propio `conflicto.rs` construían `Conflicto` sin `tipo`. No compila,
pero **si se hubiera arreglado con `Default`** habría metido un tipo incorrecto
en silencio. Se rellenó a mano.

## 4 · Verificado

```
[OK] el epoch fuera de cota NO llega al store
[OK] la rama queda anotada para cuarentena
[OK] sin cota, un epoch alto se acepta (compatibilidad)
[OK] epoch normal: aceptados=1 guardados=1
[OK] conflictos persistidos como hechos: 1
[OK] y se pueden releer del store: 1 hecho(s)
[OK] tras 'reiniciar', 1/1 conflictos siguen legibles
[OK] la cadena de conflictos verifica
```

**284 tests en `lumen-nodo`, todos verdes.**

La cota es **opcional** (`None` = comportamiento anterior): no rompe a quien no
la usa.

## 5 · Lo que sigue sin estar

- **La cuarentena no se persiste.** Vive en el `ResumenRecepcion` de esa llamada.
  Si el nodo reinicia, olvida qué ramas había apartado — **el mismo error que
  corregimos con los conflictos**, ahora un nivel más arriba.
- **`sim_flota` no usa `recibir_hechos_con_cota`.** La flota de simulación sigue
  sin cota.
- **El escrow sigue sin existir.** Los conflictos de recurso se detectan y se
  registran, pero nada impide que dos ramas reserven el mismo recurso.

## 6 · Estado del diseño de reconvergencia

| Pieza | Construida | Cableada |
|---|:---:|:---:|
| Tipado de hechos | ✅ | ✅ |
| Digest recalculable | ✅ | ⬜ solo en tests |
| Hecho de conflicto | ✅ | ✅ |
| Cota de epoch | ✅ | ✅ |

**Falta cablear el digest** y persistir la cuarentena. Lo demás está en uso.
