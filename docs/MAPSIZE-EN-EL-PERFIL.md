# `MAPSIZE` en el perfil — una sola fuente de verdad

> 2026-11-24. Cierra la inconsistencia que quedaba: el tamaño de mapa era la
> única pieza de la durabilidad que vivía fuera del perfil.

---

## 1 · Qué había

| Pieza | De dónde venía | Estado |
|---|---|---|
| `durabilidad` | **perfil** | ✅ |
| `durabilidad_lote` | **perfil** | ✅ |
| `mapsize_mb` | **variable de entorno** | ❌ fuera del perfil |

Y el crecimiento automático ya funcionaba: si el mapa se llena, se duplica y se
reintenta. **El riesgo real ya estaba cubierto**; lo que faltaba era coherencia.

## 2 · Qué cambia

`mapsize_mb` pasa a ser campo del perfil, con valores por tipo de nodo:

| Perfil | `mapsize_mb` | por qué |
|---|---:|---|
| **config** | 64 | estado de agentes, poco volumen |
| **barco** | 512 | 40 barcos × 21.600 ≈ 420 MB |
| **enjambre** | 1.024 | muchos nodos efímeros |
| **ledger** | 8.192 | 1 M de usuarios ≈ 2,5 GB/día |

Y `PerfilReplicacion::aplicar_al_entorno()` lo aplica antes de abrir el store.
**Una sola fuente: el perfil.**

## 3 · El `mapsize` es un SUELO, no un techo

Esto es lo importante y conviene no confundirlo:

- El valor del perfil es **de dónde se parte**.
- Si se llena, el store **crece solo** (duplica) y reintenta.
- Techo real: **1.400 MB en 32 bits** (espacio de direcciones), sin techo en 64.

Así que un `mapsize` mal puesto **no pierde datos**: como mucho arranca con más o
menos reserva. Es muy distinto de la durabilidad, donde un valor equivocado sí
puede costar escrituras.

## 4 · Validación

```rust
mapsize_mb == 0              -> error
mapsize_mb > 1400 en 32 bits -> error
```

El caso del **ledger en 32 bits** es el interesante: pide 8 GB, que **no caben**
en un nodo ARMv7. El perfil lo rechaza al validarse, en vez de fallar al escribir.

**Ese es el límite que ya habíamos identificado**: un nodo de 32 bits no puede ser
hub de un ledger. Ahora lo dice el sistema, no un documento.

## 5 · Verificado

```
cada_perfil_declara_su_mapsize        OK   64 / 512 / 1024 / 8192
un_mapsize_de_cero_es_invalido        OK   rechazado
en_32_bits_el_mapa_tiene_techo        OK   1401 MB rechazado en 32 bits
```

Los 4 perfiles JSON cargan con su `mapsize_mb`.

**Flota sin pérdidas tras el cambio:**

| Barcos | Hechos | Aceptados |
|---:|---:|---:|
| 20 | 240.000 | **240.000** |
| 40 | 240.000 | **240.000** |
| 40 | 480.000 | **480.000** |

**205 tests en `lumen-nodo`, todos verdes.**

## 6 · Lo que queda de la durabilidad

Ya no queda nada fuera del perfil. Las tres piezas que deciden cómo se escribe
—fsync, agrupación de commits y tamaño de mapa— se configuran en el mismo sitio.

**`LUMEN_LMDB_NOSYNC` y `LUMEN_LMDB_MAPSIZE_MB` se siguen leyendo** del entorno
por compatibilidad, pero el camino recomendado es el perfil.
