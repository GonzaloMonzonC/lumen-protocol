# Partición: diagnóstico y estado

> 2026-11-26. **La prueba de partición no está terminada.** Este documento existe
> para que la próxima vez se empiece por donde toca, no por adivinar.

---

## 1 · Qué se quería probar

El escenario del paper del enjambre:

```
1. Dos hubs, cada uno con su mitad de la flota    ✅ funciona
2. Cada mitad escribe en su hub (partición)       ✅ funciona
3. Se restablece el enlace: convergen             ❌ NO funciona
```

## 2 · Lo que sí funciona

**Los dos hubs, con sus mitades, replicando sin pérdidas.** Eso está probado:

```
H1: FIN barcos=2 aceptados=100 rechazados=0
H2: FIN barcos=2 aceptados=100 rechazados=0
```

## 3 · La causa exacta del fallo, ya encontrada

Se diagnosticó con trazas en los dos lados:

```
TRAZA hub: 1 pedido(s) de serie
TRAZA hub: no abre LMDB .../H: LMDB open(...)
```

**El hub SÍ recibe la petición de serie.** Lo que falla es que el **hilo de la
conexión intenta abrir el LMDB que el hilo principal ya tiene abierto**.

**LMDB no admite dos aperturas del mismo entorno en el mismo proceso** con
configuración distinta. El hilo no puede tener su propio host sobre el mismo
directorio.

## 4 · La solución correcta

**El hilo tiene el socket; el principal tiene el host.** Hay que pasarse los datos:

```
hilo  --(pedido: nodo, serie)-->  principal
hilo  <--(respuesta: mensajes)--  principal
```

Con dos canales `mpsc`:

- `tx_pedido` / `rx_pedido` — el hilo pide, el principal escucha
- `tx_respuesta` / `rx_respuesta` — el principal responde, el hilo recibe

El principal, mientras espera el `join()` de sus hilos, atiende los pedidos:

```rust
for (hilo, rx, rx_pedido, tx_respuesta) in pendientes {
    // Atender pedidos de serie mientras el hilo vive.
    while let Ok((nodo_pedido, serie)) = rx_pedido.try_recv() {
        let msgs = hechos_wire::mensajes_de_serie(&host, &nodo_pedido, &serie, "");
        let _ = tx_respuesta.send(msgs.iter().map(|m| m.body.clone()).collect());
    }
    let (recibidos, error, nodo_detectado) = hilo.join()...;
}
```

**Lo que NO hay que hacer** (ya se intentó y falló):
- Abrir un segundo `MemoryHost` desde el hilo → *"LMDB open"* falla.
- Leer el LMDB desde el hilo con una ruta propia → mismo problema.

## 5 · Otros fallos encontrados por el camino

| # | Qué | Estado |
|---|---|---|
| 1 | El hub cerraba al recibir el último barco y no aceptaba la reunión | ✅ `LUMEN_MARGEN_CONEXIONES` |
| 2 | La petición de serie no decía de qué nodo | ✅ `SERIE\|<nodo>\|<serie>` |
| 3 | `contar_serie`/`leer_serie` devolvían 0 para hechos de instancia | ✅ **arreglado de raíz** |
| 4 | El hub no puede abrir LMDB desde el hilo | ⬜ **este documento** |

## 6 · Estado del código

**El modo `reunir` de `sim_flota` se perdió** al hacer `git stash` (el `pop` no lo
restauró). Hay que reescribirlo, pero ahora **con el canal en el diseño**, no
descubriéndolo por el camino.

Lo que hay que rehacer:
1. Subcomando `reunir` en `sim_flota`
2. `mensaje_peticion_serie(nodo, serie)` y `peticion_de_serie()` en `hechos_wire`
3. `mensajes_de_serie(host, nodo, serie, "")` con `leer_todas_las_ramas`
4. Los dos canales en el hub

**Nada de eso está commiteado.** Se perdió.

## 7 · Lo que sí está commiteado y sirve

| Commit | Qué |
|---|---|
| `a2f4e3c2` | Arreglo de raíz de `contar_serie`/`leer_serie` (295 tests) |
| `858199da` | Flota con defensas: cota de epoch probada con 40 barcos |
| `4ba720e5` | Cuarentena persistida y digest en uso |
| `4a92ae07` | Cableado de las cuatro piezas |

## 8 · La lección de esta sesión

**Cuando un fallo deja de enseñarte algo, para.**

Estuve varias vueltas tocando código sin capturar la salida del hub. En cuanto la
capturé (redirigiendo stdout **y** stderr a un fichero, en vez de leer de un
PIPE), la causa apareció en **una línea**.

El tiempo perdido no fue por el problema técnico: fue por **no ver lo que el
programa decía**.
