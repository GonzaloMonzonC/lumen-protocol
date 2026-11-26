# Por qué Ed25519 es 45× más lento en la NAS — y qué implica para Raspberry

> 2026-11-24. No hay Raspberry disponible. Lo que se puede hacer sin ella:
> **entender de qué depende el coste**, para saber qué mejora y qué no.

---

## 1 · Las cifras medidas

| Operación | PC i7 | NAS Armada-370 | Factor |
|---|---:|---:|---:|
| SHA-256 por hash | 20 µs | **50 µs** | 2,5× |
| Verificar Ed25519 | 78 µs | **3.555 µs** | **45×** |

Estabilidad comprobada: 3 pasadas de 5.000 verificaciones dan 17.541 / 19.136 /
16.801 ms. Variación ±8%, normal en ARMv7 de 2014.

## 2 · El dato que lo explica: normalizado por ciclo

| Operación | Ciclos en NAS | Ciclos en PC | Por ciclo |
|---|---:|---:|---:|
| SHA-256 | ~60.000 | ~80.000 | **0,7×** |
| Verificar Ed25519 | **~4.266.000** | ~312.000 | **13,7×** |

*NAS a 1,2 GHz, PC a ~4,0 GHz efectivos.*

**SHA-256 necesita MENOS ciclos en la NAS que en el PC.** Su desventaja de 2,5×
es puramente frecuencia. La implementación es igual de buena.

**Ed25519 necesita 13,7× más ciclos.** Eso no es frecuencia: es **arquitectura**.

## 3 · El motivo está en `/proc/cpuinfo`

```
Features: swp half thumb fastmult vfp edsp vfpv3 vfpv3d16 tls
```

El Armada-370 **no tiene**:
- **NEON** (SIMD). `vfpv3d16` es FPU escalar básica, no vectorial.
- **Instrucciones criptográficas** (`aes`, `sha1`, `sha2`, `crc32`).

Curve25519 es aritmética de enteros de 256 bits sobre campo finito. Se implementa
como operaciones de 64 bits encadenadas, y con SIMD se procesan varias en
paralelo. **Sin NEON, todo es escalar.**

SHA-256, en cambio, es inherentemente secuencial (cada bloque depende del
anterior), así que **no gana tanto con SIMD** — por eso no se resiente.

## 4 · Qué implica para Raspberry Pi 4/5

Sin poder medir, lo honesto es decir **qué cambia y qué no**:

| Factor | NAS Armada-370 | Raspberry 4/5 | Efecto sobre Ed25519 |
|---|---|---|---|
| **NEON** | ❌ | ✅ | **el factor grande**: vectoriza field ops |
| Frecuencia | 1,2 GHz | 1,5 / 2,4 GHz | 1,2–2× |
| Núcleos | **1** | **4** | 4× en paralelo (series distintas) |
| Cripto ARMv8 | ❌ | ✅ | poco efecto: Ed25519 no la usa |

**Ed25519 no usa las instrucciones criptográficas de ARMv8** — es software puro.
Lo que le ayuda es **NEON** (vectorizar) y **frecuencia**.

**Estimación razonable, y marcada como estimación:**
- Por el NEON: el factor 13,7× por ciclo debería caer a un rango de 2–4×.
- Por frecuencia: otro 1,2–2×.
- **Total: 3.555 µs → entre 300 y 800 µs por verificación.**

Eso pondría la verificación de 21.600 hechos en **6–17 segundos** (frente a 77 s
en la NAS), y con 4 núcleos en paralelo por series distintas, **2–5 s**.

**Sin medirlo no se puede afirmar.** Es una estimación con base, no un dato.

## 5 · Lo que NO hay que esperar de Raspberry

- **No hará la firma individual gratis.** Ni con NEON, verificar 21.600 firmas
  costará segundos de CPU.
- **Los sellos seguirán siendo la opción correcta.** Con sellos, la NAS ya tarda
  1,7 s; en Raspberry serían décimas.
- **El paralelismo por series** (2,8× en el PC con 8 núcleos) sí aplicará en
  Raspberry con 4 núcleos.

## 6 · La conclusión que ya no depende de Raspberry

**La decisión de firmar por bloque no está en duda.** En la NAS reduce el coste de
verificación de 75 s a 1,7 s (**43×**). En una Raspberry mejorará el número
absoluto, pero **la proporción se mantiene**: agrupar 100 hechos por firma sigue
siendo 100× menos operaciones de curva.

Lo que Raspberry cambiaría es **cuánto se puede hacer sin sellos**, no si hacen
falta.

## 7 · Lo que haría falta para cerrarlo de verdad

1. **Una Raspberry Pi 4 o 5** (prestada, comprada o en la nube). Cualquier modelo
   con ARMv8 sirve.
2. El binario ya está: `bench-cadenas` se compila con
   `--target aarch64-unknown-linux-gnu` y se ejecuta igual. **Cinco minutos.**
3. Sin ella, la estimación de la sección 4 es lo más honesto que se puede dar.

## 8 · Nota de método

Se intentó compilar con `-C target-feature=+neon` para medir la diferencia, y
**Rust lo rechaza**: el Armada-370 no tiene NEON, así que ese target no lo admite.
Eso confirma en la práctica lo que dice `/proc/cpuinfo`.

No se han inventado cifras de Raspberry. Lo que hay es una estimación con el
razonamiento explícito, y la lista de lo que falta para convertirla en medición.
