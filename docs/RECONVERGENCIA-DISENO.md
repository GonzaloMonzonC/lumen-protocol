# Reconvergencia del split-brain — diseño

> 2026-11-26. Revisado por **Poli**, **Smith** y **Zalo** por separado.
> Los tres encontraron fallos de fondo en el planteamiento inicial.
> Este documento recoge el diseño corregido **y los fallos que se descartaron**.

---

## 0 · Qué pide el paper y qué tenemos

**El paper** (los dos papers del enjambre) pide:

> *"reconciliando los árboles de estado **sin conflictos** mediante marcas
> temporales de **orden total** e inmutables"*

**Lo que tenemos:** cuando la red se parte, las dos ramas coexisten con su cadena
intacta y el conflicto se registra **con evidencia de los dos hashes**. Nunca se
descarta nada.

**Lo que falta:** que al reencontrarse, el enjambre vuelva a operar como uno.

---

## 1 · El error de planteamiento inicial (y quién lo destapó)

Mi primera idea fue:

> *"Separo hechos de estado: los hechos nunca se descartan, el estado converge a
> uno. Así el enjambre vuelve a volar como uno, pero la caja negra conserva la
> partición."*

**Poli lo aceptó con una condición, y Smith lo destrozó por otra vía.**

### Fallo 1 — "convergencia ≠ corrección" (Smith)

> *"Dos ramas reservan el mismo volumen de aire → converge perfectamente a un
> estado con doble asignación. **No has diseñado un fallo de divergencia, has
> diseñado una divergencia exitosa.**"*

**Esto hunde la idea ingenua de "unir todo y ya converge".** Un conjunto que
converge a un estado **incorrecto** es peor que uno que diverge, porque el fallo
pasa desapercibido.

### Fallo 2 — "elegir no borra, pero sí borra del estado" (Poli)

> *"Si un hecho de la rama perdedora cambiaba el estado, ese cambio **sí
> desaparece** del estado vigente. No del log, pero operativamente es como si no
> hubiera ocurrido. La diferencia con el bug anterior es que ahora es **auditable
> y reversible**, no silencioso."*

**Es una mejora, no magia.** Y hay que decirlo así.

### Fallo 3 — "LWW sobre seguridad es un error de categoría" (Smith)

> *"Si un hecho nuevo puede revocar una asignación ya actuada, eso no es estado:
> es historia que crece, y la acción antigua debe seguir justificada para
> siempre."*

**No se puede aplicar "el último gana" a decisiones de seguridad.** Un dron que
ya ejecutó un viraje evasivo lo hizo; no se puede reescribir que no lo hizo.

### Fallo 4 — "el veneno es AHORA" (Smith)

Si `f` consulta *"el epoch máximo que conozco localmente"*, dos réplicas con
conocimiento parcial calculan cosas distintas. **Llamar pureza a eso es un
accidente**, no un diseño.

### Fallo 5 — "un dron comprometido fabrica epoch 2^63" (Smith)

Con orden total por epoch, **quien tenga la clave de un dron gana siempre**, y
como el merge es monótono, es un **estado absorbente irreversible**.

**Sin consenso no se previene. Solo se detecta.** Y eso hay que decirlo en voz alta.

---

## 2 · El diseño corregido

### 2.1 Los tres planos, separados

Zalo lo zanjó:

> *"A 1 kHz es inviable y además es el plano equivocado. Separa planos: control
> (1 kHz, local, **no toca escrow**) vs gobernanza (1–10 Hz, escrow solo para
> recursos exclusivos)."*

| Plano | Frecuencia | Toca escrow | Replica |
|---|---|---|---|
| **Control** | 1 kHz | ❌ nunca | El estado local de vuelo |
| **Telemetría** | 1–50 Hz | ❌ | Hechos, unión simple |
| **Gobernanza** | 1–10 Hz | ✅ | Escrow de recursos exclusivos |

**El vuelo normal no transfiere propiedad.** Si hiciera falta escrow por ciclo de
control, el diseño estaría mal.

### 2.2 Hechos tipados — sin esto no hay nada (Poli)

> *"Si tratas todos los hechos como iguales, tendrás hechos huérfanos que nadie
> sabe si importan. Sin tipado, la separación es cosmética."*

| Tipo | Convergencia | Ejemplo |
|---|---|---|
| **Idempotente** | unión | "el dron X está en (lat, lon, alt)" |
| **Conmutativo** | unión | "la batería está al 47%" |
| **Con revisor** | **conflicto explícito** | "el dron X reserva este volumen" |
| **Nunca LWW** | **commit + revocación** | "el dron X cambia a modo RTH" |

**Un hecho de seguridad no se sustituye: se revoca con otro hecho que lo dice.**

### 2.3 Propiedad por recurso, no por tiempo (Smith + Zalo)

> Smith: *"No consensúes el tiempo. **Particiona la propiedad.** Celdas con dueño
> único; propiedad = cadena firmada de escrow."*
>
> Zalo: *"La celda no es territorio, es **quién puede emitir hechos sobre el
> recurso X**. No hay propiedad de zona móvil; hay escrow sobre recursos
> exclusivos. Un dron al cruzar no hereda zona: suelta escrow, entra, pide uno
> nuevo."*

**Un recurso exclusivo** (volumen de aire, carril, ventana de aterrizaje) tiene
**un solo emisor** en cada momento. Solo él puede emitir hechos sobre él.

Eso elimina el doble uso **por construcción**, no por regla de desempate.

### 2.4 Conflictos: explícitos o nada (Smith)

> *"Sin hecho de conflicto explícito, la unión es una pérdida silenciosa."*

Cuando dos ramas tienen hechos incompatibles sobre el mismo recurso:

1. Se emite un **hecho de conflicto** firmado
2. El recurso entra en **cuarentena**
3. Decide un **operador humano** (o una política declarada)

**No se resuelve implícitamente por `max`.** Nunca.

### 2.5 Epoch acotado, no libre (Smith + Zalo)

> Smith: *"Epoch causalmente justificado: `epoch = 1 + max(epoch de los sellos
> padre que cita)`. Mata el salto arbitrario."*

Y una cota adicional:

> Zalo: *"epoch > local + drift → no absorbes, marcas cuarentena."*

**Un salto imposible no se acepta: se pone en cuarentena y se avisa.** Es
detectar, no prevenir — que es lo único honesto sin consenso.

### 2.6 Digest recalculable — la obligación que no se puede saltar

> Smith: *"Poder recalcular desde cero y comparar digest entre réplicas. **Si no
> puedes recalcular, no tienes CRDT, tienes gossip con esperanza.**"*

Cada nodo debe poder:
1. Recalcular el estado desde los hechos, desde cero
2. Publicar el digest del resultado
3. Otro nodo compara: si difieren, hay un bug del aplicador

**Sin esto, un bug de materialización es divergencia permanente** aunque la
función sea pura.

---

## 3 · Qué es "convergencia" y qué no

**Convergencia** = todas las réplicas calculan el mismo estado desde los mismos
hechos. Es matemática y se puede probar.

**Corrección** = el estado es el adecuado. **No es lo mismo**, y Smith fue claro:
un enjambre puede converger perfectamente a un estado donde dos drones creen ser
dueños del mismo aire.

| | Se prueba | Cómo |
|---|---|---|
| **Convergencia** | sí | digest igual en todas las réplicas |
| **Corrección** | no | requiere política + operador |

**El diseño garantiza la primera. La segunda es decisión de producto.**

---

## 4 · Qué se puede construir en semanas y qué no

| | Esfuerzo |
|---|---|
| Tipado de hechos | **semanas** |
| Digest recalculable entre réplicas | **semanas** |
| Hecho de conflicto explícito | **semanas** |
| Cota de epoch (cuarentena) | **semanas** |
| Escrow de recursos exclusivos | meses |
| Escrow **móvil** completo | años |
| BFT real / consenso | **años** |
| Verificación formal | años |

**Lo de "semanas" es lo que da valor inmediato.** Lo de años no se toca.

---

## 5 · La salida honesta que planteó Zalo

> *"Si el split-brain ya funciona y la reconvergencia es tan difícil, quizá no hay
> que hacerla. Quizá basta con detectar el conflicto y dejar que el operador
> humano decida. ¿Es una salida honesta o es cobarde?"*

Su respuesta:

> *"Híbrido: **recursos idempotentes convergen solos**; conflictos de seguridad →
> hecho explícito, cuarentena, decisión humana. Detectar+parar+operador es
> correcto para lo segundo, **cobarde si lo aplicas a todo**."*

**Ese es el diseño.** Y es mucho más honesto que prometer convergencia total.

---

## 6 · Lo que ningún test da (Smith)

> *"Partición **asimétrica** y larga (los tests usan simétricas); tormenta de merge
> al curar (40 drones sincronizando a la vez, backpressure QUIC); LMDB con
> escritor único → free list creciendo y disco llenándose; operador **bizantino**
> con build tocado; crecimiento real a 30 días; corrupción de hardware sobre la
> evidencia. **Solo el soak de semanas lo dice.**"*

Nada de esto se puede demostrar hoy con lo que tengo en local. **Decirlo es parte
del diseño.**

---

## 7 · Resumen en cinco líneas (Zalo)

```
- Hechos firmados grow-only, unión; estado = f(hechos, contexto citado), nunca "ahora".
- Tipar: idempotente / conmutativo / LWW-solo-no-seguridad / requiere revisión.
- Propiedad por recurso, no por tiempo; escrow firmado, un solo emisor.
- Conflicto semántico = hecho explícito + cuarentena, jamás pérdida silenciosa.
- Epoch acotado y digest recalculable; convergencia ≠ corrección.
```

---

## 8 · Lo que este documento NO dice

- **No promete consenso.** No lo hay y no es necesario para lo que se construye.
- **No promete corrección.** Solo convergencia.
- **No hay soak de 40 drones.** Las particiones que se prueban son las que yo
  invento, y Smith avisa que las simétricas son las fáciles.
- **El escrow móvil no está diseñado.** Solo el escrow de recursos exclusivos, y
  ni eso está construido todavía.
