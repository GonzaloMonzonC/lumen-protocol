# `MAPSIZE` — por qué un número fijo no sirve

> 2026-11-24. Pregunta de Gonzalo: *"¿un mapsize de 1 GB no sería descabellado?"*
> Respuesta corta: **no es descabellado para barcos, y es insuficiente para
> ledger.** El problema no es el número, es que sea fijo.

---

## 1 · 1 GB por ámbito

| Ámbito | Hechos/día | 1 GB aguanta |
|---|---:|---|
| **40 barcos** (1 Hz, 6 h) | 864.000 | **~24 días** ✅ |
| **Enjambre de 1.000 drones** (10 Hz) | 10.000.000 | **~2 días** ⚠️ |
| **Ledger cripto, 1 M usuarios** (5 tx/día) | 5.000.000 | **~4 horas** ❌ |
| **Ledger serio** (referencia Visa) | 1.000.000.000 | **~1 minuto** ❌ |

*Cálculo con ~500 B por hecho (valor + hash 64 hex + firma 128 hex + metadatos + overhead LMDB).*

**Para barcos, 1 GB da casi un mes.** Es razonable.

**Para el ledger que describes, 1 GB no llega ni a una tarde.**

## 2 · El techo duro: 32 bits

Y hay algo peor que el tamaño: **en 32 bits el mapa no puede pasar de ~1,4 GB**.

```rust
// Esto YA está en lmdb_store.rs
if cfg!(target_pointer_width = "32") && mapsize_mb > 1400 {
    mapsize_mb = 1400;
}
```

Un nodo ARMv7 (el caso de la NAS, kernel 3.2) **no puede tener más de 1,4 GB de
mapa, punto**. No es configuración: es el espacio de direcciones del proceso.

**Consecuencia:** un nodo de 32 bits no sirve como hub de un ledger. Sirve como
nodo de barcos, y con retención.

## 3 · Por qué un número fijo es el error de raíz

Elegir `MAPSIZE` al arrancar obliga a **adivinar el futuro**:

- Si pones poco → `MDB_MAP_FULL` en producción, con el sistema perdiendo datos.
- Si pones mucho → reservas un espacio de direcciones enorme que puede no caber
  (sobre todo en 32 bits).
- Y **no puedes cambiar de idea sin reiniciar**.

Para un barco, adivinar es fácil: sabes cuántas muestras por hora. Para un
ledger con usuarios que crecen, **es imposible**.

## 4 · LMDB sí sabe crecer — y no lo estamos usando

`mdb_env_set_mapsize()` existe y permite **ampliar el mapa en caliente**, sin
cerrar el entorno ni perder datos:

```c
int mdb_env_set_mapsize(MDB_env *env, size_t size);
```

Está en el vendor (`lmdb-master-sys/src/bindings.rs:261`). **No se usa.**

La secuencia correcta ante `MDB_MAP_FULL` es:

1. Detectar el error (hoy se descarta: ese fue el bug que costó horas).
2. Calcular el tamaño actual con `mdb_env_info()`.
3. Ampliar con `mdb_env_set_mapsize()` — el doble, por ejemplo.
4. **Reintentar la escritura.**

Sin reiniciar, sin perder nada, sin adivinar.

## 5 · La propuesta

### 5.1 `MAPSIZE` como **suelo**, no como techo

- El valor de arranque es una **estimación inicial**, no una promesa.
- Si se llena, el nodo **crece solo**, con un aviso en el log.

### 5.2 En el perfil, junto a la durabilidad

| Perfil | `mapsize_inicial` | Crecimiento |
|---|---:|---|
| barco | 512 MB | sí, hasta 1,4 GB (32 bits) |
| enjambre | 1 GB | sí |
| ledger | 8 GB | sí, sin techo en 64 bits |
| config | 64 MB | no hace falta |

### 5.3 `MDB_MAP_FULL` con nombre propio

Hoy es un string dentro de un `Host(...)` anidado:

```
guardar: Host("\"LMDB commit(set): MDB_MAP_FULL: Environment mapsize limit reached\"")
```

Debería ser `ErrorAlmacen::MapaLleno { ocupado, limite }`. Es un error **esperable
y recuperable**, no una excepción genérica.

## 6 · Y una pregunta de fondo que conviene hacerse ahora

**¿LMDB es el motor correcto para un ledger de millones de usuarios?**

| | LMDB | Lo que pide un ledger |
|---|---|---|
| Escritura | **un escritor a la vez** | muchos en paralelo |
| Mapa | uno por proceso | distribuido |
| Escala | vertical (más disco) | horizontal (más nodos) |
| Retención | todo en el mapa | histórico fuera |

**LMDB es un motor de un solo escritor.** Para barcos es perfecto: cada barco
escribe lo suyo. Para un ledger con millones de usuarios **escribiendo a la vez**,
el cuello no será el mapa: será que **solo puede escribir uno cada vez**.

Eso no se arregla con `MAPSIZE`. Se arregla con **sharding**: cada nodo es dueño
de un rango de cuentas, y la replicación ya está resuelta. El ledger no es un
nodo grande: es **muchos nodos pequeños**, cada uno con su LMDB.

## 7 · Resumen

| Pregunta | Respuesta |
|---|---|
| ¿1 GB es descabellado? | No. Para barcos da ~24 días |
| ¿Basta para el ledger? | No. 1 GB = ~4 h con 1 M usuarios |
| ¿Cuál es el número bueno? | **Ninguno fijo**: que crezca solo |
| ¿Puede crecer LMDB? | **Sí**, `mdb_env_set_mapsize`, y no lo usamos |
| ¿Es LMDB el motor del ledger? | Sí, **pero con sharding**, no como nodo único |
