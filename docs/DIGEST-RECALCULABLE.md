# Digest recalculable — detectar que dos réplicas materializaron distinto

> 2026-11-26. Segunda pieza del diseño de reconvergencia.
> Código: `lumen-nodo/src/digest.rs`

---

## 1 · Por qué existe

Smith, en la revisión del diseño:

> *"Poder recalcular desde cero y comparar digest entre réplicas. **Si no puedes
> recalcular, no tienes CRDT, tienes gossip con esperanza.**"*

El problema: aunque la función de convergencia sea pura, **el código que la
aplica puede tener un bug**. Un aplicador malo produce divergencia permanente y
silenciosa — dos nodos con los mismos hechos y estados distintos, sin enterarse.

Con un digest, se detecta en el acto.

## 2 · Las tres reglas que lo hacen determinista

1. **Se ordenan los hechos antes de derivar.** Por `(nodo, serie, seq,
   instance_id)`. El orden de llegada **no puede** cambiar el resultado: en una
   red los paquetes llegan desordenados.
2. **Se usa `BTreeMap`, no `HashMap`.** Un `HashMap` recorre en orden distinto en
   cada ejecución y el digest cambiaría solo.
3. **El tipo del hecho entra en el digest**, para que un cambio de regla de
   convergencia se vea.

**No se usa `ts`** — los relojes de los nodos no están sincronizados. Lo dijo
Smith: *"el veneno es AHORA"*.

## 3 · Lo que se comprobó

```
[OK] mismo conjunto en orden distinto -> MISMO digest
[OK] el diagnostico dice: iguales
[OK] recalcular desde cero == incremental
[OK] perder el hecho VIGENTE de una clave -> DIVERGEN
[OK] el digest senala la clave concreta: ["clave-3"]
```

Y algo que el test destapó y **conviene tener claro**:

```
[OK] perder un hecho NO vigente NO cambia el estado (correcto)
```

**Borrar un hecho intermedio no altera el estado.** Para el estado es correcto:
solo cuenta el vigente. Pero significa que **el digest no detecta la pérdida de un
hecho intermedio** — y eso **no es un fallo**: para eso está la cadena de hashes.

| Pregunta | Quién la responde |
|---|---|
| ¿Falta un hecho intermedio? | **Cadena de hashes** |
| ¿Dos réplicas calcularon lo mismo? | **Digest** |
| ¿Está este hecho concreto? | **Merkle** |

**Tres comprobaciones distintas, tres mecanismos distintos.** Confundirlas es
cómo se acaba con un sistema que dice "todo bien" sin haber comprobado lo que
importa.

## 4 · El diagnóstico dice QUÉ clave falla

No basta con *"divergen"*. Si el diagnóstico no señala la clave, el bug es
indepurable.

```
claves distintas: ["clave-3"]
solo en buena:    []
solo en mala:     []
```

Con eso, un operador sabe exactamente dónde mirar.

## 5 · Lo que este digest NO resuelve

- **No compara el conjunto de hechos.** Dos nodos tras una partición tienen
  hechos distintos y **digests distintos**, y eso es correcto: no han fusionado
  todavía. Distinguir "divergencia por bug" de "divergencia por partición" exige
  comparar también los hechos, y eso lo hará la reconvergencia.
- **No resuelve conflictos.** Deriva un estado con una regla simple
  (último por orden canónico). La regla completa del diseño (epoch, conflicto
  explícito, cuarentena) se construye encima.
- **No detecta hechos intermedios perdidos.** Para eso, la cadena.

## 6 · Estado del diseño

| Pieza | Estado |
|---|---|
| **Tipado de hechos** | ✅ |
| **Digest recalculable** | ✅ |
| Hecho de conflicto explícito | ⬜ |
| Cota de epoch (cuarentena) | ⬜ |
| Propiedad por recurso (escrow) | ⬜ meses |

**252 tests en `lumen-nodo`, todos verdes.**

Con tipado y digest, la reconvergencia ya tiene sobre qué apoyarse: sabe **qué
clase de hecho** es cada uno, y sabe **cómo detectar** que dos nodos calcularon
distinto. Lo que falta es la fusión en sí.
