# `pump_estado()` — cierra la ambigüedad también en el ciclo completo

> 2026-11-24. Completa lo que se empezó con `poll_estado`: `pump()` también
> arrastraba el `0` ambiguo.

---

## 1 · Qué faltaba

Se arregló `poll()` con `Lectura { Datos, Vacio, Cerrado }`, pero **`pump()` seguía
devolviendo `(enviados, recibidos)`** — un contador donde `0` significa dos cosas,
igual que antes.

Quien usaba `pump` no tenía forma de saber si el par cerraba. Y el barco de la
simulación lo usaba para esperar el ACK: si el hub cerraba, **esperaba los 20 s
completos** del contador antes de rendirse.

## 2 · La pieza nueva

```rust
pub fn pump_estado(&mut self, znet: &mut Znet) -> Result<(usize, Lectura), QuicZnetError>
```

- `enviados`: cuántos mensajes salieron.
- `lectura`: `Datos(n) | Vacio | Cerrado`, sin ambigüedad.

**`pump()` se conserva** para no romper a quien ya lo usa.

## 3 · El efecto inmediato

El barco de la simulación esperaba así:

```rust
// antes: si el hub cerraba, seguía esperando hasta agotar 20.000 vueltas
match qz.pump(&mut znet) {
    Ok((_e, recibidos)) => { if recibidos > 0 { ... } }
    ...
}
```

```rust
// ahora: si el hub cierra, se sabe en el acto
match qz.pump_estado(&mut znet)? {
    (_, Lectura::Cerrado) => { fallo_flujo = "el hub cerro"; break; }
    (_, Lectura::Datos(_)) => { /* leer el ACK */ }
    (_, Lectura::Vacio)    => {}
}
```

**Un cierre se detecta al instante en vez de tras 20 s de espera.**

## 4 · Verificado

```
pump_estado_distingue_cierre_de_vacio              OK
pump_estado_entrega_los_mensajes_y_dice_cuantos    OK
```

**31 tests en `lumen-znet`.**

Y la flota sigue sin pérdidas:

| Barcos | Hechos | Aceptados |
|---:|---:|---:|
| 20 | 240.000 | **240.000** |
| 40 | 240.000 | **240.000** |
| 40 | 480.000 | **480.000** |

## 5 · Estado de la ambigüedad

| Capa | Antes | Ahora |
|---|---|---|
| `Transport::read` | `0` ambiguo | **sin cambios** — se resuelve arriba |
| `poll` | `0` ambiguo | ✅ `Lectura` |
| `pump` | `(env, 0)` ambiguo | ✅ `pump_estado` |

`Transport::read` se queda como está **a propósito**: es el trait que comparten
stdio, SHM y QUIC, y ninguno de los otros dos lo necesita. La distinción se hace
en la capa de QUIC, que es donde importa.

**La ambigüedad ya no llega a ningún llamante.**

## 6 · Lo que queda

- **Verificación de flota en el hub**: el hub comprueba cadena y firmas, pero no
  que el certificado del barco esté firmado por la raíz del armador. La función
  `verificar_miembro` ya existe sin conectar.
