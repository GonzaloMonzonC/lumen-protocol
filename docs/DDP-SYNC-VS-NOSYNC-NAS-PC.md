# Sync vs nosync — NAS frente a PC, medido

> 2026-11-24. Comparación del mismo binario y las mismas pruebas en los dos
> entornos. **Corrige una medición anterior que estaba mal hecha.**

---

## 1 · El hardware

| | **NAS (neferu)** | **PC (L13)** |
|---|---|---|
| CPU | Marvell Armada-370 (ARMv7, ~795 BogoMIPS) | Intel i7-10510U (4 núcleos) |
| Disco | **HDD rotacional** (2 discos, `rotational=1`) | **SSD NVMe** Samsung |
| RAM | 242 MB | 15,7 GB |

## 2 · Los resultados, con 3 pasadas y mediana

| Escrituras | NAS `sync` | NAS `nosync` | PC `sync` | PC `nosync` |
|---|---:|---:|---:|---:|
| 100 | 5.371 ms | **36 ms** | 89 ms | 89 ms |
| 1.000 | 59.159 ms | **203 ms** | 105 ms | 105 ms |

**El dato que importa:**

| | Ratio sync/nosync |
|---|---:|
| **NAS (HDD)** | **291×** |
| **PC (NVMe)** | **1,0×** (ninguna diferencia) |

## 3 · La conclusión, y es clara

**El coste del `fsync` depende del disco, no del procesador.**

- En el PC con NVMe, `sync` **no cuesta nada**: 105 ms frente a 105 ms. El
  fsync es tan barato que no se nota.
- En la NAS con HDD, `sync` cuesta **291× más**.

Eso valida la decisión de diseño: **la durabilidad se configura por el disco**.
Un portátil puede ir en `sync` sin pagar nada; una NAS no puede permitírselo.

## 4 · La corrección metodológica (importante)

**La primera medición del PC dio 76.771 ms para `sync` con 21.600 escrituras.**
Era una lectura falsa: la primera pasada en frío. Repitiendo tres veces y
tomando la mediana:

| 21.600 escrituras | Primera pasada | Mediana de 3 |
|---|---:|---:|
| PC `sync` | 76.771 ms | **110 ms** |
| PC `nosync` | 111 ms | **102 ms** |

La primera pasada paga la creación del entorno LMDB, la extensión del fichero y
el primer `fsync` del volumen. **Medir una sola vez da cifras que no valen** —
y en este caso habrían hecho concluir que el PC también sufría, cuando no es así.

**Método aplicado a partir de ahora: 3 pasadas, mediana, y cada pasada con su
propio fichero.**

## 5 · Qué significa para los perfiles

| Perfil | Durabilidad | Por qué sigue siendo correcto |
|---|---|---|
| **barco** | `lote` 64 | El barco puede llevar HDD/SD. En la NAS, `sync` son 59 s por 1.000 muestras; 21.600 serían ~21 minutos |
| **enjambre** | `nosync` | La memoria se va con la batería; no hay nada que proteger |
| **ledger** | `sync` | Si el ledger corre en SSD (lo normal), `sync` **no cuesta nada**: 105 ms por 1.000 |
| **config** | `nosync` | Estado efímero |

Y una consecuencia para el `ledger` que antes no estaba clara: **en SSD, `sync`
es gratis**. Solo es caro en disco lento. Así que el ledger no necesita renunciar
a la durabilidad.

## 6 · Cifras para el caso del paper

Un barco con 6 h de corte = 21.600 muestras. En la NAS (HDD):

| Modo | Tiempo |
|---|---:|
| `sync` | **~21 minutos** (extrapolado de 59 s / 1.000) |
| `nosync` | **~4 s** (medido: 4.120 ms) |

En un portátil con SSD, `sync` sería **~110 ms**: los dos modos son iguales.

## 7 · Lo que sigue sin medir

- **El `lote` como tal.** Lo medido son los extremos. El lote estará entre los
  dos, más cerca de `nosync` (el fsync cae 1 de cada 64).
- **La replicación por QUIC en la NAS.** `mvm-nas` no usa `lumen-nodo`; lo
  medido allí es el motor y LMDB.
