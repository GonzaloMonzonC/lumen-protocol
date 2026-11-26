# Coste real de verificar — el cuello de un ledger

> 2026-11-24. Medido en el PC (i7-10510U, 8 hilos). Lo que de verdad cuesta
> verificar hechos firmados, y qué hace falta para que un ledger de millones de
> usuarios sea viable.

---

## 1 · El dato que importa

| Hechos | Verificar todas las firmas | Cadena + sellos |
|---:|---:|---:|
| **21.600** (un barco, 6 h) | **1,6 s** | **0,6 s** |
| 240.000 (40 barcos) | 18,3 s | 7,0 s |
| 1.000.000 | 76,6 s | 29,2 s |
| 10.000.000 | **12,7 min** | **4,9 min** |

**Coste por hecho:** ~76 µs verificando cada firma, ~29 µs con cadena + sellos.

## 2 · El hallazgo: el coste NO son las firmas

Desglose con 21.600 hechos:

| Componente | Tiempo | µs/hecho |
|---|---:|---:|
| Solo sellos (216 firmas Ed25519) | 179 ms | **8,3** |
| **Solo cadena (21.600 SHA-256 encadenados)** | **432 ms** | **20,0** |
| Cadena + sellos | 636 ms | 29,5 |

**La cadena de hashes cuesta 2,4× más que todas las firmas del bloque.**

Eso corrige una intuición extendida: no es la criptografía de curva elíptica lo
que pesa, es **encadenar SHA-256 hecho por hecho**.

Y tiene una consecuencia práctica: **optimizar la firma no sirve de mucho**; lo
que habría que optimizar es el recorrido de la cadena.

## 3 · Firmar por bloque: 3×, no 100×

| | Tiempo (21.600) |
|---|---:|
| Firmar por hecho | 1.285 ms |
| Firmar por bloque (216 sellos) | 346 ms |

**3,7× al firmar** (216 firmas en vez de 21.600), pero al **verificar** la
ganancia total es solo 3× porque la cadena se paga igual.

Es decir: la firma por bloque **sigue mereciendo la pena** (barco: 21.600
firmas serían mucha batería), pero **no es la bala de plata** que parecía.

## 4 · Paralelismo: 2,8× con 8 núcleos

La cadena es secuencial **dentro de una serie**, pero **series distintas son
independientes**. En un ledger, cada cuenta es una serie.

```
100 series x 200 hechos = 20.000 hechos
  secuencial -> 2.449 ms
  paralelo   ->   874 ms   (2.8x)
  series verificadas OK: 100/100
```

**2,8× con 8 núcleos**, no 8×: se crean hilos por tanda y eso cuesta. Pero es
ganancia real y sin dependencias nuevas (usa `std::thread::scope`).

Implementado en `hechos_store::verificar_series_en_paralelo`.

## 5 · Qué significa para el ledger

Con **sharding** (cada nodo dueño de un rango de cuentas), el paralelismo es
natural: cada nodo tiene muchas series y las verifica a la vez.

Estimación para un nodo con 100.000 cuentas × 50 hechos/día:

| | Hechos | Tiempo |
|---|---:|---:|
| Un día de un nodo | 5.000.000 | **4,9 min** solo |
| Con paralelismo real (8 núcleos, 2,8×) | 5.000.000 | **~1,7 min** |

**Viable**, siempre que no se verifique todo de golpe al recibir.

## 6 · Las tres estrategias posibles

1. **Verificar por lotes al recibir** — no bloquear la recepción.
2. **Verificar en paralelo por serie** — ya implementado, 2,8×.
3. **Verificar en diferido**: aceptar marcando "sin verificar", verificar en
   background, y **no servir** un hecho sin verificar a quien lo pida.

La 3 es la que permite absorbers picos, pero exige poder responder "no lo tengo
verificado todavía", que es un estado más del sistema.

## 7 · Lo que NO se ha medido

- **En la NAS ARMv7.** Los 76 µs son del i7. En ARM el coste será varias veces
  mayor, y ahí la cadena pesará todavía más.
- **Verificación durante la recepción** con carga concurrente: aquí se mide
  aislamiento, no el hub atendiendo 40 barcos y verificando a la vez.
- **Coste de guardar** (LMDB) separado del de verificar.

## 8 · Conclusión

**El sistema es viable para un ledger**, pero no por la firma por bloque: por
**sharding + paralelismo + verificación diferida**.

Y el dato que cambia prioridades: **lo caro es la cadena de hashes, no las
firmas**. Cualquier optimización futura debería empezar por ahí.
