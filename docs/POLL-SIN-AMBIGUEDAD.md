# `poll()` sin ambigüedad — `Vacio | Cerrado`

> 2026-11-24. Cierra la deuda que señaló Poli en la revisión.
> Código: `lumen-znet/src/quic_backend.rs` · `Lectura`

---

## 1 · El problema

`poll()` devolvía un `usize` donde **`0` significaba dos cosas distintas**:

- el par **cerró** el stream (fin de conexión)
- **no llegó nada** en esta vuelta

Con esa ambigüedad, quien llama **tiene que adivinar**. Y la única forma de
adivinar es contar vueltas sin datos:

```rust
// el hub de la simulación, antes
if n == 0 {
    sin_datos += 1;
    if sin_datos > 6000 { break; }   // ← ¿y si solo va lento?
}
```

Ese contador **cortaba conexiones vivas** con volumen alto. Le pasó al hub con
62.291 hechos perdidos — aunque la causa real de esa pérdida concreta fuera el
`MAPSIZE`, la heurística estaba ahí y era una bomba esperando.

Lo dijo **Poli** en la revisión: *"`poll()` colapsa tres estados en uno"*.

## 2 · La solución

Un enum explícito:

```rust
pub enum Lectura {
    Datos(usize),  // llegaron n mensajes completos
    Vacio,         // no hay frames todavía — LA CONEXIÓN VIVE
    Cerrado,       // el par cerró el stream
}
```

Y `poll_estado()` que lo devuelve.

**`poll()` se queda igual.** No se rompe nada de lo que ya lo usa: los tests
antiguos, el `pump`, el `bench`. El camino nuevo es aditivo.

## 3 · El caso que de verdad importaba

**Media trama no es un cierre.**

Si llegan bytes pero no completan un frame, la conexión está **viva** y el resto
llegará. Confundir eso con un cierre es justo el fallo que producía cortes
prematuros.

```rust
let completo = serializar(&[...]);
let media = completo[..completo.len() / 2].to_vec();  // cortada por la mitad
// antes:  poll() -> 0   (indistinguible de "cerrado")
// ahora:  poll_estado() -> Lectura::Vacio
```

## 4 · Verificado

```
el_cierre_del_stream_se_ve_como_cerrado        OK   stream vacío -> Cerrado
media_trama_se_ve_como_vacio_no_como_cierre    OK   media trama -> Vacio
un_frame_completo_se_ve_como_datos             OK   frame -> Datos(1)
el_lector_puede_seguir_hasta_cerrado_sin_adivinar  OK  sin contadores
```

**43 tests en `lumen-znet`, 202 en `lumen-nodo`, todos verdes.**

## 5 · El hub ya no adivina

`sim_flota.rs` pasó del contador de vueltas al estado explícito:

```rust
match qz.poll_estado(&mut znet)? {
    Lectura::Datos(_) => { vueltas_vacias = 0; }
    Lectura::Vacio    => { sleep(2ms); }      // la conexión vive
    Lectura::Cerrado  => break,                // fin de verdad
}
```

Queda una **red de seguridad** de 60 s sin datos ni cierre, que es una protección
contra un bloqueo, no una heurística para detectar el fin.

## 6 · Medido: igual o mejor

Flota completa tras el cambio:

| Barcos | Hechos | Aceptados | Rechazados |
|---:|---:|---:|---:|
| 20 | 240.000 | **240.000** | 0 |
| 40 | 240.000 | **240.000** | 0 |
| 40 | 480.000 | **480.000** | 0 |

**Cero pérdidas.** Y el código del receptor deja de depender de un temporizador.

## 7 · Lo que sigue pendiente

1. **`pump()` también arrastra la ambigüedad**: devuelve `(enviados, recibidos)`
   sin estado. Un `pump_estado()` sería lo coherente. Hoy no hace falta porque el
   hub usa `poll_estado`, pero es la misma deuda a medio cerrar.
2. **`Transport::read` sigue devolviendo `usize`** con `0` ambiguo en `quic.rs`.
   La distinción se hace en `poll_estado` mirando el `read`, así que el trait
   queda como está. Cambiarlo obligaría a tocar stdio y SHM.
3. **`MAPSIZE` como campo del perfil** — sigue siendo variable de entorno, con
   crecimiento automático.
