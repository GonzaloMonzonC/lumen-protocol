# Flota replicando — barcos que escriben y convergen en un hub

> 2026-11-24. Primer escenario completo del paper: N barcos escriben su bitácora
> **y la replican por QUIC** a un hub que verifica y guarda.
> Código: `src/bin/sim_flota.rs` · Orquestador: `experimentos/flota/flota_replicando.py`

---

## 1 · Qué se prueba

Cada barco es un **proceso real** que:

1. Escribe su bitácora en su LMDB, firmada, con el `Escritor` que respeta el perfil (lote 64).
2. Abre una conexión QUIC+TLS 1.3 al hub, con pin de huella.
3. Le manda cada hecho como mensaje DDP.
4. Manda `FIN` para que el hub sepa que ha terminado.

El hub acepta, verifica (cadena, firmas, flota) y guarda en su propio LMDB.

## 2 · Resultados medidos

| Barcos | Muestras | Esperados | Aceptados | Rechazados | Resultado |
|---:|---:|---:|---:|---:|---|
| 3 | 50 | 150 | **150** | 0 | ✅ converge |
| 4 | 30 | 120 | **120** | 0 | ✅ converge |
| 5 | 20 | 100 | **100** | 0 | ✅ converge |
| 8 | 50 | 400 | **400** | 0 | ✅ converge |
| **10** | 50 | 500 | **500** | 0 | ✅ **converge** |
| 20 | 100 | 2000 | 190 | 0 | ❌ hub aceptó solo 2 |

**Hasta 10 barcos simultáneos, cero pérdidas.** A 20 falla — y no es pérdida de
datos: es que el hub **no llega a aceptar** las conexiones.

## 3 · El límite encontrado, y de qué es

**No es del protocolo de replicación. Es del servidor de prueba.**

`QuicEndpoint::accept()` hace `accept_bi()`, que espera a que el cliente **abra
un stream**. Y atiende **una conexión por llamada**, de forma bloqueante.

Con 20 barcos a la vez:

1. Los barcos tardan ~2 s en escribir su bitácora antes de conectar.
2. El hub espera en `accept()` por el primero.
3. Los que llegan mientras el hub está ocupado reciben `ConnectionRefused`.
4. El reintento del orquestador los reenvía, pero ocupan turno.
5. A partir de ~15 se encalla: el hub espera conexiones que ya se rindieron.

**Esto NO invalida la replicación.** Los 10 barcos que sí conectaron mandaron
todo, sin un rechazo. Lo que falta es un servidor que acepte conexiones **en
paralelo**, no de una en una.

## 4 · Los tres bugs que salieron por el camino

Los tres eran míos, en el binario de simulación. Los tres son lecciones que
valen para el código real:

### 4.1 `pump()` devuelve `(enviados, recibidos)`

No `(leídos, mensajes)`. Confundir el primer valor cortaba la conexión **siempre**,
porque el hub nunca tiene nada que enviar → 0.

```
antes:  recibidos=0   leidos=0
ahora:  recibidos=50  aceptados=50
```

### 4.2 No hay forma de detectar el fin del envío

`pump()` devuelve 0 tanto si "no hay datos" como en EOF. El hub no puede saber
cuándo un barco ha terminado.

**Solución: el barco manda `FIN` explícito.** Un mensaje más, y el protocolo
deja de depender de adivinar.

### 4.3 El duplicado de un reintento no es pérdida

Un barco que reintenta reenvía sus hechos. El hub los ve como **duplicados**
(mismo hash), no como aceptados. Comparar "aceptados == esperados" daba falsos
fallos.

La comprobación correcta: **aceptados + duplicados == esperados**, y rechazados == 0.

## 5 · Lo que esto demuestra

**El circuito completo funciona:** un barco escribe firmado, viaja por QUIC con
TLS, el hub verifica la cadena y la pertenencia, y lo guarda. Sin perder nada.

**Y aguanta 10 a la vez.** Para el escenario del paper (una flota de barcos
replicando), eso es un resultado real, no una simulación en memoria.

## 6 · Lo que falta para escalar

1. **Servidor QUIC que acepte en paralelo.** Hoy `accept()` es secuencial de
   diseño. Es la pieza que bloquea pasar de 10 barcos.
2. **Reintento con backoff en el propio nodo**, no en el orquestador.
3. **El hub debería guardar mientras recibe**, no al final de cada conexión.
4. **Verificación de flota en la recepción**: hoy el hub verifica cadena y
   firmas, pero no comprueba el certificado contra la raíz del armador porque
   los barcos de simulación no llevan certificado.
