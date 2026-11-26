# Cierre de la reconvergencia — y el bug que apareció al cerrarla

> 2026-11-26. Últimas dos piezas cableadas: cuarentena persistida y digest en uso.
> **Y en el proceso apareció un bug real de producción.**

---

## 1 · Lo que se cerró

### Cuarentena persistida

La cuarentena vivía en memoria: al reiniciar, el nodo **olvidaba qué ramas había
apartado** y las volvía a admitir sin revisión. **El mismo error que corregimos
con los conflictos**, un nivel más arriba.

Ahora es una **serie de hechos** (`cuarentena`), como todo lo demás:

```
accion=apartar; motivo=epoch 0 -> 9999: salto de 9999, cota 1...
accion=liberar; motivo=revisado por operador
```

Ventajas de que sea una serie y no una tabla aparte:
- Se guarda en la PDB/LMDB **como todo lo demás**.
- Queda **firmada y encadenada**: nadie borra una cuarentena sin que se note.
- Hay **historia**: cuándo se apartó y cuándo se liberó.

`reconstruir()` recorre los eventos y se queda con el último por rama: si una rama
se apartó y luego se liberó, **no está en cuarentena**.

### Digest en uso

`digest_de_rama()` y `comparar_digest()` calculan el digest **en el nodo**, no solo
en tests. Dos nodos intercambian 32 bytes y saben si han materializado lo mismo.

## 2 · EL BUG DE PRODUCCIÓN

Y este es el hallazgo del día.

### Síntoma

El test decía: **5 eventos de cuarentena, solo 1 guardado.**

### Causa

```rust
let seq = hechos_store::contar_serie(host, nodo, SERIE_CUARENTENA);  // ← MAL
```

`contar_serie` cuenta la rama **principal** (instancia `""`):

```rust
.get(NS_HECHOS, &subs(nodo, serie, n, ""))   // ← instancia ""
```

Pero los eventos se guardan en la instancia del nodo (`"hub"`). Así que
`contar_serie` devolvía **0 siempre**, y **todos los eventos se escribían en
`seq 0` y se sobrescribían entre sí**.

**Cinco eventos de cuarentena, uno guardado. Los otros cuatro, perdidos en
silencio.**

### Alcance

El mismo bug estaba en **`persistir_conflictos`**: los conflictos también se
escribían en `seq 0`. **Si había tres conflictos, solo quedaba el último.**

Es exactamente el tipo de fallo que el diseño quería evitar: *"jamás pérdida
silenciosa"*.

### Arreglo

Nueva función `contar_serie_rama(host, nodo, serie, instancia)`, y las dos
llamadas corregidas.

```
antes:  5 eventos -> 1 guardado
ahora:  5 eventos -> 5 guardados y encadenados
```

## 3 · La lección, que ya apareció dos veces

**`contar_serie` y `leer_serie_de_rama` no miran lo mismo.**

- `contar_serie` → rama principal (instancia `""`)
- `leer_serie_de_rama` → la instancia que le pidas

Confundirlos **falla en silencio** con un valor plausible (0). No da error, no
avisa: simplemente escribe encima de lo anterior.

Ya me pasó una vez en un test (y lo achacré a un bug de escritura). La segunda vez
era **código de producción**.

Debería haber una sola función, o un nombre que no invite a confundirlos. Queda
apuntado.

## 4 · Tres tests mal planteados, corregidos

Al cerrar aparecieron tres tests que fallaban **por estar mal escritos**, no por
el código:

| Test | Qué creía | Realidad |
|---|---|---|
| "orden distinto → mismo digest" | B recibía al revés y guardaría todo | La cadena **rechaza** un hecho sin su predecesor. Correcto. |
| "20 hechos → 20 claves" | cada hecho es una clave | Los 20 eran de la misma clave: **1 clave**. Correcto. |
| "serie de cuarentena" | — | El bug real del `contar_serie` |

**Los dos primeros eran expectativas equivocadas mías.** El tercero era un bug de
verdad. Distinguirlos es lo que cuesta.

## 5 · Verificado

```
[OK] tras 'reiniciar', la rama sigue apartada
[OK] tras liberar, la rama vuelve a operar
[OK] 5 eventos de cuarentena encadenados y verificados
[OK] un hecho sin su predecesor se RECHAZA (correcto)
[OK] en orden, entran los 3
[OK] digests distintos -> divergencia
[OK] comparar consigo mismo no da falso positivo
[OK] mismo conjunto -> mismo digest
[OK] y derivar no depende del orden del vector
```

**290 tests en `lumen-nodo`, todos verdes.**

## 6 · Estado final del diseño de reconvergencia

| Pieza | Construida | Cableada |
|---|:---:|:---:|
| Tipado de hechos | ✅ | ✅ |
| Digest recalculable | ✅ | ✅ |
| Hecho de conflicto | ✅ | ✅ |
| Cota de epoch | ✅ | ✅ |
| Cuarentena persistida | ✅ | ✅ |

**Las cinco piezas del diseño están construidas y en uso.**

## 7 · Lo que sigue sin estar

- **`sim_flota` no usa `recibir_hechos_con_cota`.** La flota de simulación sigue
  sin cota ni conflictos persistidos.
- **El escrow no existe.** Nada impide que dos ramas reserven el mismo recurso: se
  detecta y se registra, pero no se previene.
- **La reconvergencia completa no está.** Las piezas permiten **detectar** y
  **registrar**; la fusión automática de dos ramas no se ha escrito.
- **Soak de 40 drones.** Smith avisó que las particiones simétricas son las
  fáciles y que solo semanas de prueba real dicen algo.
