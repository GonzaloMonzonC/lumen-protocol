# Cadena de custodia del epoch

> 2026-11-24. Cierra el punto 4: el epoch ya no se puede subir a lo bruto.
> Código: `src/epoch.rs` · Tests: `tests/epoch_custodia.rs`

---

## 1 · El agujero que cierra

Con `instance_id` y `epoch` (formato v2) ya se distingue una reinstalación de una
suplantación. Pero **faltaba controlar el salto**: cualquiera con la clave del
barco podía declarar `epoch = 999999` y ganar siempre en cualquier comparación.

La clave del barco ya es poderosa (firma hechos). Pero **el epoch es el orden
entre historias**. Si lo decide quien grita más alto, no hay orden.

## 2 · La regla

Cada salto de epoch va **firmado con la clave del barco sobre el epoch anterior**:

```text
E0 ──firma(E0)──▶ E1 ──firma(E1)──▶ E2 ──firma(E2)──▶ E3
```

Para estar en `E3` hay que presentar la cadena completa. **No basta con tener la
clave: hay que demostrar continuidad.**

Y el salto es **de uno en uno** (`SALTO_MAXIMO = 1`). Permitir saltos de N abriría
la puerta a "estaba en el 3 y ahora en el 1000" sin presentar los 997 pasos.

## 3 · Implementación

```rust
let salto = SaltoEpoch::crear(0, 1, "inst-NUEVA", &identidad)?;
// ...viaja con los hechos...
verificar_cadena(epoch_conocido, epoch_pretendido, &saltos, &clave) -> Custodia
```

`Custodia` distingue cinco casos, para que el operador sepa **qué** falló:

| Variante | Qué pasó |
|---|---|
| `Valido` | se llega, con cadena |
| `FaltanSaltos { desde, hacia }` | hay un hueco en la cadena |
| `FirmaInvalida { desde, hacia }` | un salto no verifica |
| `SaltoDemasiadoGrande` | un salto salta más de uno |
| `Retroceso` | el epoch pretendido es anterior |

Y está **conectado a la recepción**: `recibir_hechos_custodiados()` filtra los
hechos cuyo epoch no supera la custodia antes de guardarlos.

**El módulo solo no servía.** Un verificador que nadie llama es una ilusión de
seguridad — el mismo error que ya apareció con el sello de bloque.

## 4 · Verificado

```
[OK] reinstalacion con salto firmado (0->1)      -> Valido
[OK] epoch 999 SIN cadena                        -> FaltanSaltos { 0, 999 }
[OK] salto firmado por un impostor               -> FirmaInvalida
[OK] salto de 0 a 5 (de golpe)                   -> rechazado al crear
[OK] retroceso de epoch 5 a 2                    -> Retroceso
[OK] recepcion con epoch 99 sin cadena           -> 0 aceptados, 0 guardados
[OK] reinstalacion legitima                      -> 5 aceptados, 5 guardados
[OK] hecho v1 (sin epoch)                        -> entra sin custodia
[OK] cadena 0->1->2->3 completa                  -> Valido
[OK] cadena con el salto 1->2 quitado            -> FaltanSaltos
```

**202 tests en `lumen-nodo`, todos verdes.**

## 5 · Por qué esto NO es consenso

No hay votación ni quórum. Es una **cadena de firmas verificable**: un nodo
comprueba por sí solo si un epoch es legítimo, sin hablar con nadie.

Eso es justo lo que necesita un barco sin cobertura. El paper no pide consenso, y
meterlo habría añadido latencia y complejidad para un problema que no lo necesita.

## 6 · Lo que NO resuelve (y hay que decidirlo algún día)

**Si se pierde la clave, no se puede firmar el salto.**

El barco queda atrapado en su epoch: puede seguir escribiendo hechos, pero no
reinstalarse con uno nuevo. La única salida sería un **epoch de recuperación
firmado por la raíz del armador** — y hoy la raíz **firma certificados, no
recuperaciones**.

Está deliberadamente fuera de este módulo: **no queremos que un mecanismo
automático pueda saltarse la custodia**. Es una decisión de operador con firma de
flota, no un atajo del protocolo.

## 7 · Lo que queda

1. **Epoch de recuperación** (arriba): decidir si se añade y con qué firma.
2. **Políticas de conflicto por rama**: `por_epoch` y `por_rama`. Ahora que el
   epoch es fiable, `por_epoch` ya tiene sentido.
3. **Flota replicando a un hub** con custodia de epoch incluida.
