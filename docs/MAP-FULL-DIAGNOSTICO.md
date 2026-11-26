# El "control de flujo" no era control de flujo: era `MDB_MAP_FULL`

> 2026-11-24. Investigación completa de las pérdidas de hechos a escala.
> **Conclusión: nunca hubo un problema de flujo ni de red. El hub se quedaba sin
> espacio en el mapa de LMDB, y el error se descartaba con un mensaje genérico.**

---

## 1 · El síntoma, medido

| Barcos | Muestras | Esperados | Aceptados | "Perdidos" |
|---:|---:|---:|---:|---:|
| 2 | 12.000 | 24.000 | 24.000 | 0 |
| 20 | 6.000 | 120.000 | 120.000 | 0 |
| 20 | 12.000 | 240.000 | **177.709** | 62.291 |
| 40 | 6.000 | 240.000 | **204.072** | 35.928 |

Parecía que el emisor saturaba al receptor. **Era falso.**

## 2 · La investigación, y los dos diagnósticos equivocados

### 2.1 Consulta a Poli y Zalo

Ambos fueron claros y ambos apuntaron al sitio equivocado:

- **Poli:** *"tu `poll()` colapsa tres estados en uno: `recibidos==0` no distingue vacío de cierre"*. Cierto, y era un bug real de la API — pero **no causaba las pérdidas**.
- **Zalo:** *"no es flow control perdiendo datos; es cierre ordenado prematuro por tu lógica"*. También cierto como principio, y también apuntaba fuera.

Los dos dijeron algo valioso: **QUIC no pierde bytes en silencio**. Si se pierde, es porque alguien cierra. Tenían razón — pero el cierre no era mío.

### 2.2 Lo que probé y no funcionó

| Intento | Resultado |
|---|---|
| Ventanas de 256 con ACK por lote | 177k → 204k. Mejor, no resuelto |
| Drenar canales durante `accept` | **Peor**: bloqueaba el aceptador (18k de 120k) |
| Subir `worker_threads` de 2 a núcleos | Sin efecto |
| Aceptar conexiones en paralelo | Necesario, pero no suficiente |

Todo eso eran mejoras reales. **Ninguna era la causa.**

## 3 · La causa, encontrada al instrumentar

Cuando el hub reportó el **error real** en vez de un genérico:

```
BARCO 17 recibidos=12000 aceptados=2 rechazados=11998
    motivo=guardar: LMDB put: MDB_MAP_FULL: Environment mapsize limit reached

BARCO 20 recibidos=12000 aceptados=0 rechazados=12000
    motivo=guardar: LMDB commit(set): MDB_MAP_FULL
```

**`recibidos=12000`.** Los hechos **llegaban todos**. Fallaba **guardarlos**.

El hub tenía `LUMEN_LMDB_MAPSIZE_MB=64`. 240.000 hechos no caben en 64 MB.

## 4 · El bug de verdad: el error se descartaba

En `hechos_wire.rs`:

```rust
// ANTES
if hechos_store::guardar(host, &h).is_err() {
    r.rechazados += 1;
    r.primer_motivo.get_or_insert_with(|| "no se pudo guardar".into());
}
```

**El error de LMDB se tiraba.** `MDB_MAP_FULL` — que dice exactamente qué pasa y
cómo arreglarlo — se convertía en *"no se pudo guardar"*. Eso mandó la
investigación hacia la red durante horas.

```rust
// AHORA
if let Err(e) = hechos_store::guardar(host, &h) {
    r.rechazados += 1;
    r.primer_motivo.get_or_insert_with(|| format!("guardar: {e:?}"));
}
```

## 5 · El resultado

Con `MAPSIZE=2048`:

| Barcos | Muestras | Hechos | Aceptados | Rechazados |
|---:|---:|---:|---:|---:|
| 20 | 12.000 | 240.000 | **240.000** | **0** |
| 40 | 6.000 | 240.000 | **240.000** | **0** |
| **40** | **12.000** | **480.000** | **480.000** | **0** |

**480.000 hechos, cero pérdidas, 70 segundos.** Con 40 barcos a la vez.

## 6 · Los `connection lost` que quedan NO son pérdida

Algunos barcos muestran:

```
BARCO 21 recibidos=12000 aceptados=12000 rechazados=0
    error=QUIC read: connection lost
```

Leyendo bien: **recibió 12.000, aceptó 12.000, rechazó 0**. El aviso salta
cuando el barco cierra su lado después de recibir su ACK final. Es cosmético;
el hecho es que no se pierde nada.

## 7 · Lo que sí se arregló por el camino (y vale)

Aunque no eran la causa, estas mejoras son reales y se quedan:

1. **`aceptar_conexion()`** — el hub acepta en paralelo. Sin esto, con 20
   conexiones, el hub se encallaba esperando streams.
2. **ACK por ventana** — el emisor no llena la ventana de QUIC.
3. **Streaming por canal** — el hilo de red no acumula hechos.
4. **`workers_quic()`** — hilos del runtime según núcleos, no un 2 fijo.
5. **El error de LMDB se propaga** — el cambio más importante de todos: de aquí
   salió el diagnóstico.

## 8 · La lección

**Un mensaje de error genérico puede costar horas de investigación en la
dirección equivocada.**

`"no se pudo guardar"` parecía una precaución razonable: no exponer detalles
internos. En realidad ocultaba `MDB_MAP_FULL`, que decía literalmente cuál era el
problema y qué hacer.

Y una segunda: **consultar a otros agentes ayuda, pero ninguno tenía el dato
decisivo**, porque el dato estaba en un error que yo estaba tirando a la basura.
La instrumentación valió más que cualquier opinión.

## 9 · Lo que queda

1. **El `MAPSIZE` del hub debe dimensionarse según el volumen esperado**, no ser
   un valor fijo. Con 40 barcos × 21.600 hechos hará falta más.
2. **`MDB_MAP_FULL` debería ser un error explícito del sistema**, con nombre
   propio, no un string dentro de un `Host(...)` anidado.
3. **La distinción `Vacio | Cerrado` en `poll()`** sigue pendiente (lo señaló
   Poli y es correcto), aunque no causara esto.
4. **Dejar de tirar errores en mensajes genéricos** en el resto del código.
