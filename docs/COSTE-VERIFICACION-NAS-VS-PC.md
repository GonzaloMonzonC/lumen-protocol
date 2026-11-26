# Coste de verificar — PC frente a NAS (ARMv7)

> 2026-11-24. Medido en los dos entornos con el mismo criterio.
> **En ARM la conclusión se invierte: la firma por bloque pasa de "mejora" a
> "imprescindible".**

---

## 1 · El hardware

| | PC (L13) | NAS (neferu) |
|---|---|---|
| CPU | Intel i7-10510U, 8 hilos | Marvell Armada-370, 1 núcleo ARMv7 |
| Disco | SSD NVMe | HDD rotacional |
| Kernel | Windows | **Linux 3.2.101 (2014)** |

## 2 · Los números

| Operación (por hecho) | PC i7 | NAS ARMv7 | Factor |
|---|---:|---:|---:|
| Cadena SHA-256 | 20,0 µs | **40 µs** | 2× |
| Firmar Ed25519 | ~60 µs | **1.052 µs** | 17× |
| **Verificar Ed25519** | 78 µs | **3.555 µs** | **45×** |
| Verificar sellos (bloque 100) | 8,3 µs | **82 µs** | 10× |

Medido con 21.600 hechos (6 h de un barco a 1 Hz), 3 tamaños concordantes
(1.000, 5.000 y 21.600): la tasa es estable, no es ruido.

## 3 · La conclusión se invierte

**En el PC:** la cadena cuesta 2,4× más que todas las firmas del bloque. Parecía
que lo caro era encadenar hashes.

**En la NAS:** verificar las firmas individuales cuesta **43× más** que verificar
los sellos (3.555 µs vs 82 µs por hecho). **La criptografía de curva elíptica
domina por completo.**

**Motivo:** SHA-256 tiene aceleración por hardware y está muy optimizado; Ed25519
en un ARMv7 sin aceleración criptográfica es **45× más lento que en un i7**.

## 4 · Qué significa para cada perfil

| Hechos | Verificar cada firma | Cadena + sellos |
|---:|---:|---:|
| **21.600** (un barco, 6 h) | **76,8 s** | **1,8 s** |
| 240.000 (40 barcos) | 14 min | **20 s** |
| 1.000.000 | 59 min | **1,4 min** |

**En la NAS, un hub con 40 barcos tarda 20 s en verificar una ronda completa con
sellos, y 14 minutos con verificación individual.**

## 5 · La decisión de diseño que esto valida

El perfil de barco usa `firma: por_bloque` desde el principio. La razón original
era **la batería del barco** (21.600 firmas se la comen).

**Ahora hay una segunda razón, más importante: el hub no puede verificar 21.600
firmas por barco.** Con 40 barcos serían 864.000 verificaciones Ed25519 en un
ARMv7 = **14 minutos por ronda**.

La firma por bloque no es una optimización. **Es lo que hace viable el sistema en
hardware modesto.**

## 6 · Lo que NO se ha medido

- **Verificación en paralelo en la NAS:** el Armada-370 tiene **1 núcleo**, así
  que el paralelismo que da 2,8× en el PC **no aplica**. Ese es un límite duro.
- **Con el hub atendiendo 40 barcos a la vez** (aquí se mide aislamiento).
- **Aceleración criptográfica:** el Armada-370 no tiene instrucciones AES/SHA
  dedicadas. Una Raspberry Pi 4/5 **sí** las tiene, y sería mucho más rápida.
  **Las cifras de la NAS son una cota pesimista.**

## 7 · Consecuencia para el diseño

| Nodo | Papel razonable |
|---|---|
| **NAS ARMv7** (1 núcleo, sin cripto HW) | Guardar y replicar con firma por bloque. **No** verificar todo. |
| **Raspberry Pi 4/5** (4 núcleos, cripto HW) | Hub completo, con paralelismo. |
| **PC** | Desarrollo, hubs grandes. |

Y una regla que sale de aquí: **el perfil debe declarar `firma: por_bloque`
siempre que el nodo vaya a verificar más de unos miles de hechos.** Con
verificación individual, un ARM modesto no aguanta.

## 8 · Nota sobre el método

El primer intento de medición dio cifras sin sentido (cadena = 0 ms, tara = 846 ms)
porque el binario construía la serie de hashes **antes** de la fase `nada`, y esa
construcción se contaba como tiempo de arranque.

Corregido: `nada` no hace nada, y la tara bajó a 13 ms. Las cifras de esta página
son las buenas.

Y el banco tuvo que ser un crate aparte (`bench-cadenas`) porque el de
`lumen-nodo` arrastra `ring`, que al compilar para ARM desde Windows pide
`-ladvapi32` y rompe el enlace. Para medir verificación no hacen falta ni QUIC ni
LMDB: solo Ed25519 y SHA-256.
