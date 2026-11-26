# El bug de `contar_serie` / `leer_serie` — cerrado de raíz

> 2026-11-26. El fallo que apareció **tres veces** en una sola sesión.

---

## 1 · Qué pasaba

`contar_serie` y `leer_serie` solo miraban la rama **principal** (instancia `""`):

```rust
.get(NS_HECHOS, &subs(nodo, serie, n, ""))   // ← instancia ""
```

Los hechos que llegan de un nodo con identidad van en **su** instancia (`inst-A`,
`hub`, `inst-B-A`, ...). Así que las dos devolvían **0** para series reales.

## 2 · Por qué es tan peligroso

**No da error.** Devuelve un número plausible — `0` — y el llamante concluye *"no
hay hechos"*. No hay excepción, no hay aviso, no hay log.

Se parece a un sistema que funciona y no tiene datos.

## 3 · Falló tres veces en la misma sesión

| # | Dónde | Síntoma |
|---|---|---|
| 1 | `persistir_conflictos` | 3 conflictos → **1 guardado**. Se sobrescribían en `seq 0`. |
| 2 | `persistir_evento` (cuarentena) | 5 eventos → **1 guardado**. |
| 3 | Lectura de series para reconvergencia | El hub **no encontraba nada** que dar a otro nodo. |

La primera vez se arregló con una función nueva (`contar_serie_rama`). **La
segunda y la tercera fueron el mismo bug otra vez**, porque el arreglo había sido
local y no de raíz.

## 4 · El arreglo de raíz

### `contar_serie`

Ahora cuenta **posiciones ocupadas**, sea cual sea la instancia:

```rust
loop {
    if instancias_en_posicion(host, nodo, serie, n).is_empty() { break; }
    n += 1;
}
```

### `leer_serie`

Devuelve una entrada por posición: prefiere la rama principal si existe y, si no,
la primera instancia presente.

### Y una función aparte para todas las ramas

`leer_todas_las_ramas()` devuelve **todas** las instancias. Necesaria para
split-brain: dos ramas del mismo nodo son 4 posiciones y 8 hechos.

**Esas dos cantidades son distintas a propósito:**

| Función | Devuelve |
|---|---|
| `contar_serie` | **posiciones** (4 en el ejemplo de dos ramas) |
| `leer_serie` | una por posición (4) |
| `leer_todas_las_ramas` | **todas** las ramas (8) |
| `contar_serie_rama` | las de **una** instancia |

## 5 · Verificado

```
[OK] contar_serie cuenta los hechos de una instancia con identidad (antes: 0)
[OK] leer_serie devuelve los 10 (antes: vacío)
[OK] y la cadena verifica
[OK] la rama principal (instancia '') sigue contando bien
[OK] dos ramas: contar=4, leer_serie=4, todas_las_ramas=8
[OK] una serie que no existe sigue dando 0 (no un falso positivo)
```

**295 tests en `lumen-nodo`, todos verdes.** Ninguno roto: la rama principal
—donde van los hechos de los tests existentes— se comporta igual.

## 6 · La lección

**Un fallo que devuelve un valor plausible es peor que uno que lanza.**

Este no rompía nada visiblemente: hacía que el sistema creyera que no había datos.
Y por eso volvió tres veces — cada vez lo arreglé donde se veía el síntoma, no
donde estaba la causa.

Lo que habría evitado las tres: **una sola función**, o nombres que no inviten a
confundirlas. `contar_serie` vs `contar_serie_rama` se parecen demasiado.

## 7 · Lo que sigue pendiente

**La prueba de partición no funciona todavía.** El arreglo de raíz era condición
necesaria, pero no suficiente: el hub no responde a la petición de serie y no he
conseguido ver por qué (su salida no se captura en la prueba).

Eso queda **aparcado**, con el código del modo `reunir` guardado aparte.

La partición es el escenario del paper y **no está probada**. Decirlo es parte del
estado del proyecto.
