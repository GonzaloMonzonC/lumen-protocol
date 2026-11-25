# Escenarios DDP — estudio

> Estudio previo a tocar código, 2026-11-24.
> Todo lo que aparece marcado **VERIFICADO** está leído en el código o ejecutado.
> Lo que es opinión va marcado como tal, con quién lo dijo.

## 0 · Resumen en tres frases

1. **La sincronización tal como está no propaga cambios de valor: solo claves nuevas.** Es una pérdida silenciosa de datos.
2. **El mecanismo incremental correcto ya está escrito y está desconectado.** Parece que hay fase 2 y no la hay.
3. **La intuición de Gonzalo es la arquitectura correcta**: bootstrap completo primero, incremental después. Hoy solo existe la mitad de la fase 1.

---

## 1 · Tres piezas distintas que se llaman DDP

| Pieza | Dónde | Qué hace | Estado |
|---|---|---|---|
| **lumen-znet** | `implementations/rust/lumen-znet/` | Transporte de mensajes sobre frames LUMEN. Cabecera 6 B. | ✅ 31 tests |
| **pdb_sync_engine** | `implementations/python/pdb-sync/` | Sincronización de estado PDB local↔edge | 🟡 §2 |
| **ddp_client.rs** | `lumen-m-light/src/` | Cliente HTTP+HMAC contra `vm_api` | ✅ existe |

`lumen-znet` **no sincroniza**: transporta. La sincronización es otra capa.

---

## 2 · Qué hace hoy la sincronización — VERIFICADO

`pdb_sync_engine.push_full_diff(ns)`:

1. Descarga **todas** las claves del edge paginando desde `"1970-01-01"`
   (tope 200 páginas × 500 = 100.000).
2. Lee **todas** las claves locales con `SELECT subkey, value FROM _globals`.
3. `missing = set(local_map) - edge_keys` → **diferencia de conjuntos de CLAVES**.
4. Empuja solo las que faltan.

### Fallo A — solo detecta claves nuevas · VERIFICADO (lectura)
```python
missing = sorted(set(local_map) - edge_keys)
```
Si una clave existe en ambos lados con **valor distinto**, no está en `missing`.
**No se sincroniza.** El comentario del código dice "compara el contenido REAL",
pero compara claves. → **Falta prueba empírica (escenario E3).**

### Fallo B — cada sync se baja la base entera · VERIFICADO (lectura)
Arranca en 1970 y pagina todo. Coste **O(base)**, no O(cambios).

### Fallo C — el journal incremental está desconectado · VERIFICADO (comentario del propio código)
`push_pending()` usa cursor de secuencia: **eso sí sería delta de verdad**.
Pero el código admite literalmente:
> "El journal (WAL) del SyncEngine nunca se alimenta en el flujo real
> (MVM/scripts/vm_api escriben directo a _globals) → `push_pending` devuelve
> applied=0 SIEMPRE"

### Fallo D — sin tombstones · VERIFICADO (no hay tabla ni campo de borrado)
Los borrados **no se propagan en ninguna dirección**. Peor: si el edge la tiene
y el local no, puede **resucitar**.

---

## 3 · Escenarios

| # | Escenario | Pregunta | Hoy |
|---|---|---|---|
| E1 | Nodo vacío → hub con datos | ¿Se lleva todo? ¿Cuánto tarda? | 🟡 solo claves, no valores |
| E2 | Hub con datos → nodo vacío | Igual, inverso | 🟡 idem |
| E3 | **Clave modificada en local** | ¿Sube el cambio o se pierde? | 🔴 **se pierde (A)** |
| E4 | **Modificada en ambos lados** | ¿Quién gana? ¿Pérdida silenciosa? | 🔴 no se detecta |
| E5 | **Clave borrada en un lado** | ¿Se borra o resucita? | 🔴 no se propaga (D) |
| E6 | Sync interrumpido a mitad | ¿Se reanuda sin duplicar? | 🟡 falta marca de agua |
| E7 | Dos nodos al mismo namespace | ¿Convergen? | 🔴 por diseño no |
| E8 | Base 100K claves, 1 cambio | ¿Cuánto tarda? | 🔴 O(base) |
| E9 | Nodo offline mucho tiempo | ¿Cuánto reconcilia? | 🔴 sin retención de log |
| E10 | Fallo de red a mitad de push | ¿Se corrompe? | 🟡 at-least-once por cursor |
| **E11** | **Split-brain / doble escritor con edge caído** | Añadido por Poli | 🔴 no contemplado |

**E3, E4, E5 y E11 son los que pueden estar perdiendo datos hoy.**

---

## 4 · Lo que dicen Poli, Smith y Zalo

### Poli — orden de gravedad
Dos pasadas, con **discrepancia** entre ellas (útil, no ruido):

- **1ª pasada:** A > C > B > D. "A es pérdida silenciosa de datos".
- **2ª pasada:** C > A > B > D. "C es el fallo raíz: el journal vacío hace que
  toda la arquitectura incremental sea decorativa. **Engaña**: parece que hay
  camino a fase 2 y no existe. A al menos es visible si comparas valores."

**Me quedo con la segunda.** C es peor porque oculta el problema.

Aportaciones concretas de Poli:
- **El bootstrap se olvida del punto de corte.** Hay que capturar la marca de agua
  **en el mismo instante** que el snapshot, o se pierden las escrituras concurrentes.
- **Falta estado `bootstrap_done` persistido por par** (nodo, par). El bootstrap
  nunca "termina" formalmente.
- **Tombstones con retención** ≥ ventana máxima de un nodo offline. Sin retención,
  un nodo offline largo resucita datos.
- **Timestamp del cliente no basta**: relojes sesgados → gana quien miente.
  Mínimo: **LWW por versión monotónica del servidor**, no por reloj de cliente.
- Añade **E11 (split-brain)** a los escenarios.

### Smith — multi-dominio
**Discrepancia con Poli, y creo que Smith tiene razón en esto:**

- **No journal aparte: `seq` en la propia tabla `_globals`.** Diff = `WHERE seq > cursor`.
  Coste O(cambios), cursor trivial. Un journal separado es frágil precisamente
  porque los escritores lo esquivan.
- **Índice `(ns, seq)`** y `content_hash` por clave para detectar divergencia barata.
- **Ancla del bootstrap:** el edge expone `snapshot(watermark=W)` con W = max(seq)
  en el corte atómico. El nodo guarda W y hace incremental `seq > W`.
- **No hace falta estado durable por par** si el edge retiene el log desde
  `min(cursor de nodos vivos)`. El cursor vive en el nodo; la retención en el edge.
- **Métrica de operación concreta:** ratio de divergencia por par
  (`hash(local)!=hash(edge) / total`), lag del cursor y antigüedad del último sync OK.
- **Seguridad:** HMAC autentica origen, **no contenido**. Validar tamaño, ACL por
  namespace, rechazo de seq no monotónico, y no fiarse del timestamp del cliente.
- **Si solo hubiera un día:** arreglar A (detectar cambios por valor vía seq/hash).
  **No haría** tombstones ni rediseño de conflictos todavía: "parecen urgentes pero
  sin A no hay nada que reconciliar".

### Zalo — producto y operación
- **Síntomas que ve el usuario:** "edito en un nodo y en el otro sigue el dato viejo";
  "reaparece lo que borré"; "se pisa el trabajo entre dos personas".
- **Lo nota primero: A** — "es lo que rompe la confianza".
- **B le da igual al cliente**: lo sufre el operador (coste, latencia).
- **C es tolerable hasta que pasa una vez** en producción; entonces es grave.
- **D es dolor solo del operador.**
- **Promesa que hoy es mentira:** "sincronización entre tus nodos" / "tus datos
  iguales en todos".
- **Promesa sostenible hoy:** "réplica de claves nuevas hacia el edge; los cambios
  y borrados se gestionan manualmente".

---

## 5 · Discrepancias que hay que resolver antes de decidir

| Tema | Poli | Smith | A decidir |
|---|---|---|---|
| Gravedad | 1ª: A>C · 2ª: C>A | A primero | **C o A primero** |
| Dónde va el `seq` | Journal con cursor | **En la tabla `_globals`** | Smith es más robusto: los escritores ya esquivan el journal |
| Estado por par | `bootstrap_done` persistido | Derivable de cursores + retención | Depende de cuánto se quiera aguantar nodos offline |
| Conflictos | LWW con versión de servidor | Epoch/term por par para split-brain | Lo mínimo: versión de servidor; split-brain documentado |

---

## 6 · Orden de trabajo propuesto (a validar con Gonzalo)

**Fase 0 — demostrar el fallo (medio día)**
1. Prueba empírica de E3: escribir clave en local, cambiarla en edge, sincronizar.
   Confirmar que **no** se propaga. Sin esto, todo lo demás es teoría.
2. Medir E8: coste real de sync con base grande y un solo cambio.

**Fase 1 — no perder datos (el mínimo serio)**
3. Diff **por valor**, no por clave. Con `content_hash` o comparación directa.
4. `seq` monotónico en `_globals` + índice `(ns, seq)`.
5. Cursor persistido en el nodo; retención en el edge.

**Fase 2 — fase incremental real**
6. Bootstrap con marca de agua atómica y `bootstrap_done` por par.
7. Activación de `push_pending` sobre el `seq` real.

**Fase 3 — borrados y conflictos**
8. Tombstones con retención y compactación.
9. Resolución por versión de servidor; split-brain documentado.

**Lo que NO se hace ahora** (aunque parezca urgente): CRDT completo, rediseño de
conflictos, adaptador MSM. Y **no** se toca `lumen-znet`, que está sano.

---

## 7 · Hipótesis a validar

- **H1:** hoy se pierden modificaciones de valor en silencio (E3). → ✅ **CONFIRMADA, ver §8**
- **H2:** el coste de sync es O(base completa), no O(cambios). → Fase 0.2
- **H3:** poner `seq` en `_globals` da fase 2 real sin cambiar el protocolo. → Fase 1
- **H4:** `lumen-znet` no necesita cambios para nada de esto. → a confirmar

---

## 8 · H1 CONFIRMADA — prueba ejecutada (2026-11-24)

Reproducción del algoritmo real de `push_full_diff` sobre SQLite en memoria
(`set(local) - set(edge)`). **No toca el edge ni la PDB real.**

| Caso | Antes | Qué hizo el sync | Resultado |
|---|---|---|---|
| **1** · Clave nueva | local `k1=original`, edge vacío | empujó `k1` | ✅ **se propaga** |
| **2** · **Valor modificado en local** | local `k1=MODIFICADO`, edge `k1=original` | **empujó NADA** | 🔴 **el cambio NO se propaga** |
| **3** · Valor modificado en el edge | local `k1=original`, edge `k1=MODIFICADO` | **empujó NADA** | 🔴 **divergencia, nadie reconcilia** |
| **4** · Clave borrada en local | existía en los dos | empujó `k2`, **no el borrado** | 🔴 **`k1` sigue en el edge** |

Salida literal del caso 2:

```
CASO 2 · valor modificado en local
  antes: local={k1:MODIFICADO}  edge={k1:original}
  empujadas: (NINGUNA)
  edge despues: {'k1': 'original'}
  -> ** FALLO CONFIRMADO **: el cambio NO se propaga
```

**Lo que esto significa en producción:** cualquier dato que se edite en un nodo
después del primer envío **se queda en ese nodo**. El edge nunca lo ve. Y no hay
error, ni aviso, ni log: el sync dice "ok, 0 aplicadas" y todo parece correcto.

Es exactamente lo que Zalo describió como síntoma de usuario: *"edito algo en un
nodo y en el otro sigue el dato viejo: no se ha guardado"*.

**Única cosa que hoy funciona: la creación de claves nuevas.** Es la mitad de la
fase 1 y nada de la fase 2.

