# Servidor QUIC paralelo — de 10 a 40 barcos

> 2026-11-24. Cierra el límite que bloqueaba la flota: el hub ya acepta
> conexiones **en paralelo**.
> Código: `src/quic.rs` (`aceptar_conexion`, `aceptar_stream`) ·
> `lumen-nodo/src/bin/sim_flota.rs`

---

## 1 · El límite que había

Con `QuicEndpoint::accept()` el hub aguantaba **10 barcos** y a partir de ahí se
encallaba:

```
20 barcos -> el hub acepto 2 y se quedo 30 s bloqueado
```

**La causa:** `accept()` hace `accept_bi()`, que espera a que el cliente **abra un
stream**. Y atiende **una conexión por llamada, bloqueante**. Mientras esperaba
datos de un barco, los demás recibían `ConnectionRefused`.

## 2 · La pieza nueva

```rust
// Devuelve en cuanto termina el handshake, SIN esperar stream.
let conexion = ep.aceptar_conexion()?;
// El stream se acepta despues, cuando el cliente lo abra.
conexion.aceptar_stream()?;
```

Dos métodos, ninguno rompe lo que había:

| Método | Qué hace |
|---|---|
| `QuicEndpoint::aceptar_conexion()` | handshake y vuelve, sin stream |
| `QuicTransport::aceptar_stream()` | espera al primer stream |
| `QuicTransport::tiene_stream()` | ¿ya hay stream? |
| `QuicEndpoint::accept()` | **sin cambios**, sigue esperando stream |

`accept()` se conserva intacto: quien lo usa hoy (tests, E2E) no se entera.

## 3 · Las tres correcciones que hicieron falta después

Aceptar en paralelo destapó tres fallos más. Los tres eran de la simulación, y
los tres son lecciones para el código real.

### 3.1 Un `break` que no salía del bucle correcto

Al encontrar `FIN`, el hub **cortaba el vaciado de la cola**. Los mensajes que
venían en el mismo lote detrás de `FIN` se quedaban sin sacar y se perdían en
silencio.

```rust
// mal:  if es_fin { break; }
// bien: if es_fin { fin = true; continue; }  // seguir vaciando
```

De 1008 a 1192 hechos. Mejor, pero seguía perdiendo.

### 3.2 El barco moría antes de que el hub leyera

**Esta era la causa principal.** El proceso barco terminaba, su socket se cerraba
y el hub se quedaba con lo que le había dado tiempo a leer.

**La solución es un ACK:** el hub responde `ACK <n>` y el barco **espera** antes
de salir. Medido: de 1192 a **2000 de 2000**.

Es el patrón de siempre en protocolos fiables: **quien envía no cierra hasta que
el otro confirma que recibió.**

### 3.3 Esperar los hilos convertía el bucle en secuencial

Primera versión del arreglo: lanzar hilo por conexión pero hacer `join()`
inmediato. Eso **anula el paralelismo**: el `accept` siguiente no llega hasta que
el barco actual termina.

Los `JoinHandle` se guardan y se juntan **al final**, después de aceptar todas.

## 4 · Resultado medido

| Barcos | Hechos | Recibidos | Aceptados | Tiempo |
|---:|---:|---:|---:|---:|
| 20 | 2.000 | **2.000** | **2.000** | **0,53 s** |
| **40** | 4.000 | **4.000** | **4.000** | **1,17 s** |

Con 20 el tiempo pasa de **30 s encallado a 0,53 s**. Y con 40 barcos, 4.000
hechos, cero rechazos, cero pérdidas.

Antes del cambio: 10 barcos como techo. **Ahora 40, y no se ha buscado el nuevo
límite.**

## 5 · Verificado

- `lumen`: **183 tests verdes** (incluye los de QUIC, sin cambios).
- `lumen-nodo`: **202 tests verdes**.

`accept()` no cambió, así que `quic_e2e`, `flota_multinodo` y los demás siguen
pasando sin tocarlos.

## 6 · Lo que queda

1. **Buscar el nuevo techo.** 40 funciona; no se ha probado 100 ni 500. El límite
   ahora debería ser CPU o puertos, no el diseño.
2. **El ACK va por circuito 0 a mano.** Funciona, pero el hub debería responder
   por **el mismo circuito** por el que llegó cada mensaje. Hoy hay un solo
   circuito por conexión y da igual; con varios, sería un bug.
3. **Guardar mientras se recibe.** El hub acumula los mensajes en memoria y los
   guarda al final de cada conexión. Con 40 barcos × 100 hechos son 4.000 hechos
   en RAM: bien. Con 40 × 21.600 serían 864.000, y ahí pesaría.
4. **Verificación del certificado de flota** contra la raíz del armador: los
   barcos de simulación no llevan certificado, así que no se comprueba.
