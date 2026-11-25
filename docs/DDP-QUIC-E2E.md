# DDP sobre QUIC real — verificado

> 2026-11-24. Cierra el punto 3: el protocolo deja de estar solo probado en
> memoria y **viaja por un socket TLS 1.3**.
> Test: `tests/quic_e2e.rs`.

---

## 1 · Qué cambia

| Antes | Ahora |
|---|---|
| Mensajes DDP construidos y pasados en memoria | **Servidor y cliente QUIC reales** |
| Sin TLS | **TLS 1.3 con certificado y pin de huella** |
| "el protocolo es correcto" | **"el protocolo funciona por el cable"** |

## 2 · Resultado

```
E2E POR QUIC REAL — 200 muestras por un socket TLS 1.3
[OK] servidor QUIC escuchando en 127.0.0.1:53640 (huella 91e36e55845dbd9b...)
[OK] cliente conectado por TLS 1.3
[OK] el barco envia 200 mensajes por el cable
[OK] el hub guarda y verifica por QUIC -> 200 muestras, 4 sellos
```

El flujo completo, sin atajos: el barco firma los sellos, los manda por QUIC, el
hub los recibe, **verifica la flota** y los guarda.

## 3 · Tres fallos de API que aparecieron

Ninguno era del protocolo: los tres eran **usar mal `lumen-znet`**. Y los tres
habrían dado un sistema que "parece funcionar" y pierde datos.

### 3.1 `pump()` devuelve 0 tanto en «no hay datos» como en EOF

El servidor cerraba la conexión a la primera lectura sin datos. El cliente veía
`connection lost` y se perdía todo lo que faltaba.

**Regla:** no se puede usar el 0 de `pump` para decidir el final. Hay que contar
lo recibido y cortar cuando ya está todo (o por intentos sin datos consecutivos).

### 3.2 `recv_circuit()` no es la cola de entrada

`pump()` mete los mensajes con `push_incoming`, que se lee con **`recv()`**.
`recv_circuit()` lee la cola de **salida** (lo que se responde).

Síntoma: el contador decía *"recibidos=200"* y la lista salía **vacía**. Un
sistema que reporta éxito y no procesa nada.

### 3.3 `reply()` ya encola; pasar por `push_incoming` duplica

El primer intento envió **400 mensajes** en vez de 200, porque metí los hechos en
la cola de entrada y luego los reencolé como respuestas.

## 4 · Lo que esto demuestra y lo que no

**Demuestra:**
- El protocolo viaja por QUIC con TLS 1.3.
- La verificación de flota funciona sobre datos que vienen de un socket.
- Los 200 hechos llegan, verifican y se guardan.
- El pin de huella del certificado funciona (cliente y servidor se reconocen).

**No demuestra todavía:**
- **Latencia ni throughput.** No hay medición de cuánto tarda por el cable.
- **Pérdida de paquetes y reconexión.** QUIC los maneja, pero aquí no se fuerza.
- **Varios nodos a la vez.** Es un barco y un hub.
- **Cortes largos.** El escenario del paper son 6 h sin cobertura; aquí se
  envía todo de golpe.

## 5 · Estado del conjunto

| Pieza | Estado |
|---|---|
| Firma Ed25519 real | ✅ |
| 4 perfiles desde fichero | ✅ |
| Persistencia LMDB | ✅ sobrevive al reinicio |
| Transporte por `lumen-znet` (memoria) | ✅ |
| **Transporte por QUIC + TLS 1.3** | ✅ **200 mensajes reales** |
| Doble defensa (cadena + sello) | ✅ |
| Idempotencia | ✅ |
| Verificación de flota | ✅ 5 casos |

**174 tests, todos verdes.**

## 6 · Lo que queda

1. **Medir por el cable.** Cuánto tarda mandar 21.600 muestras de un barco real.
   Es el número que dice si las 6 h de corte se resuelven en segundos o en minutos.
2. **Split-brain.** Ni probado ni diseñado.
3. **Compactación sobre disco.** Probada en Python, no en LMDB.
4. **Réplica parcial** para enjambres grandes.
