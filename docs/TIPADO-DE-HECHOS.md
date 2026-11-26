# Tipado de hechos — la pieza que hace real la reconvergencia

> 2026-11-26. Primera pieza implementada del diseño de reconvergencia.
> Código: `lumen-nodo/src/replicacion.rs` (`TipoHecho`), formato **v3**.

---

## 1 · Por qué hace falta

Poli, en la revisión del diseño:

> *"Si tratas todos los hechos como iguales, tendrás hechos huérfanos que nadie
> sabe si importan. **Sin tipado, la separación es cosmética.**"*

Todos los hechos pesaban lo mismo: telemetría, una reserva de espacio aéreo y un
cambio de modo de vuelo se trataban igual. La reconvergencia no puede decidir qué
hacer con un hecho si no sabe **qué clase de hecho es**.

## 2 · Los cuatro tipos

| Tipo | Convergencia | Ejemplo |
|---|---|---|
| **`Idempotente`** | unión simple, el nuevo sustituye | *"la batería está al 47%"* |
| **`Conmutativo`** | unión, el orden da igual | contadores, horas de vuelo |
| **`RecursoExclusivo`** | **conflicto explícito** | *"reservo este volumen de aire"* |
| **`ConRevision`** | **commit + revocación** | *"cambio a modo RTH"* |

```rust
TipoHecho::Idempotente.converge_solo()       // true
TipoHecho::Conmutativo.converge_solo()       // true
TipoHecho::RecursoExclusivo.converge_solo()  // false
TipoHecho::ConRevision.converge_solo()       // false
```

**Un recurso exclusivo y una decisión de seguridad no convergen solos.** Si lo
hicieran, el sistema convergería a un estado **incorrecto** — lo que Smith llamó
*"una divergencia exitosa"*.

## 3 · La decisión que importa: el tipo va FIRMADO

**El tipo forma parte del contenido canónico del hecho v3.** Si no fuera así,
alguien podría convertir un hecho de telemetría en uno de seguridad **sin
invalidar la firma**, y la regla de convergencia le obedecería.

Test que lo demuestra:

```
[OK] cambiar el tipo de v3 INVALIDA la firma
```

Es la pieza de seguridad de todo el diseño. Sin ella, el tipado sería decorativo.

## 4 · Por qué versión 3 y no añadir al v2

Los hechos v1 y v2 **ya están firmados** sin el campo tipo. Añadirlo al contenido
firmado del v2 habría invalidado **todos los hechos existentes**.

| Versión | Instancia | Epoch | Tipo |
|---|:---:|:---:|:---:|
| v1 | — | — | — |
| v2 | ✅ | ✅ | — |
| **v3** | ✅ | ✅ | ✅ |

**Los v1 y v2 se siguen leyendo y verificando.** No se re-firman (eso destruiría
la inmutabilidad).

```
[OK] hecho v1 sigue verificando
[OK] hecho v2 sigue verificando
[OK] v1 y v2 conviven en el mismo store
```

## 5 · Formato en disco

Se añade **un campo** al final de la línea:

```
v2:   valor|prev_hash|firma|ts|clave|instancia|epoch
v3:   valor|prev_hash|firma|ts|clave|instancia|epoch|tipo
```

`desde_texto` acepta 5, 7 u 8 campos según la versión. **Cero migración.**

## 6 · Lo que sigue faltando

El tipado es **una de las cinco piezas** del diseño:

| Del diseño | Estado |
|---|---|
| **Tipado de hechos** | ✅ **hecho** |
| Digest recalculable entre réplicas | ⬜ |
| Hecho de conflicto explícito | ⬜ |
| Cota de epoch (cuarentena) | ⬜ |
| Propiedad por recurso (escrow) | ⬜ meses |

**El tipado solo no hace la reconvergencia.** Hace que se *pueda* hacer: sin él,
el resto no tendría sobre qué decidir.

## 7 · Lo que esto NO cambia

- **No hay reconvergencia todavía.** Los tipos se guardan, pero nadie los usa aún
  para fusionar dos ramas.
- **No hay escrow.** `RecursoExclusivo` marca que un hecho necesita conflicto
  explícito, pero el mecanismo de propiedad no está construido.
- **El split-brain sigue igual de bien:** las dos ramas coexisten y no se
  descarta nada. El tipado no toca eso.
