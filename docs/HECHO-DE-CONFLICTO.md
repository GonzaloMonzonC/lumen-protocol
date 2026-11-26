# Hecho de conflicto — de detección en memoria a evidencia persistente

> 2026-11-26. Tercera pieza del diseño de reconvergencia.
> Código: `lumen-nodo/src/conflicto.rs`

---

## 1 · El agujero que cierra

Smith, en la revisión del diseño:

> *"Sin hecho de conflicto explícito, **la unión es una pérdida silenciosa**."*

El sistema ya **detectaba** conflictos y las dos ramas coexistían. Pero esa
detección vivía **solo en memoria**, en un `Vec` del resumen de recepción:

```rust
pub detalle_conflictos: Vec<Conflicto>,   // ← se perdía al reiniciar
```

**Un conflicto que se olvida al reiniciar es casi tan malo como uno descartado:**
el operador ya no puede auditar qué pasó.

## 2 · Qué es ahora

Un hecho normal — firmado, encadenado, en su propia serie `conflictos` — con toda
la evidencia legible:

```
motivo=recurso-disputado;
clave=DRON-1:reserva:0;
rama_a=inst:inst-A hash:0f1adefacf3b806a... epoch:0;
rama_b=inst:inst-B hash:fb9869b3b9dc15d1... epoch:0;
pendiente=operador:true
```

**Se lee sin herramientas.** Quien consulte la serie ve directamente qué pasó, con
los dos hashes de las dos ramas.

## 3 · Cuatro motivos, y quién decide cada uno

| Motivo | ¿Requiere operador? | Por qué |
|---|:---:|---|
| `valores-incompatibles` | ❌ puede tener regla | dos valores, ninguno más verdadero |
| `recurso-disputado` | ✅ **sí** | *"converge a doble asignación"* (Smith) |
| `decision-seguridad` | ✅ **sí** | un viraje ejecutado no se reescribe |
| `epoch-sospechoso` | ✅ **sí** | puede ser reinstalación o ataque |

**Tres de los cuatro exigen un humano.** No es exceso de prudencia: es que
resolverlos con una regla automática produce un estado **incorrecto pero
convergente**, que es peor que uno divergente.

## 4 · Lo que NO hace

**No resuelve el conflicto.** No elige ganador. Solo deja constancia firmada.

Eso es exactamente lo que pide el diseño:

> *"Conflicto semántico = hecho explícito + cuarentena, **jamás pérdida
> silenciosa**."*

La resolución, si la hay, será **otro hecho** que lo referencia. **Nada se
reescribe.**

## 5 · Verificado — y un test que hubo que rehacer

```
[OK] las DOS ramas siguen ahi (no se descarta nada)
[OK] el conflicto queda como hecho firmado (motivo: recurso-disputado)
[OK] los conflictos se encadenan como cualquier serie
[OK] tras cerrar y reabrir, el conflicto sigue: 1 hecho(s)
[OK] y se puede leer el motivo: Some(RecursoDisputado)
[OK] la firma sigue valida tras el disco
```

**El test del reinicio estaba mal y se rehizo.** La primera versión usaba
`MemoryHost`, que **no persiste entre procesos**: el test decía *"sobrevive al
reinicio"* pero no probaba nada. Se reescribió con **LMDB de verdad**: guardar,
cerrar el handle, reabrir.

Ese es justo el tipo de test que da falsa confianza. Queda escrito.

## 6 · Estado del diseño

| Pieza | Estado |
|---|---|
| **Tipado de hechos** | ✅ |
| **Digest recalculable** | ✅ |
| **Hecho de conflicto explícito** | ✅ |
| Cota de epoch (cuarentena) | ⬜ |
| Propiedad por recurso (escrow) | ⬜ meses |

**263 tests en `lumen-nodo`, todos verdes.**

## 7 · Lo que sigue faltando para la reconvergencia completa

- **Que el hub emita el hecho de conflicto automáticamente** al detectar uno. Hoy
  la función existe y está probada; falta engancharla a `recibir_hechos`.
- **La cuarentena**: hoy el conflicto se registra, pero el recurso disputado sigue
  en juego. Falta marcar que está bloqueado hasta que un operador decida.
- **El escrow**: el mecanismo que evitaría el conflicto de raíz (un solo emisor
  por recurso). Es de meses, no de semanas.
