# Anclaje: epoch automático y sello publicado

Cierra el **nivel A del doc 10**: *"Merkle epoch + log de transparencia — días de
trabajo, sirve a todos los verticales"*.

```
PDB  →  Merkle root por epoch  →  ^AUDIT(epoch)  →  registro publicado
        merkle_epoch.py           anclaje.py         (JSONL hoy, Rekor mañana)
```

---

## Por qué existe esta pieza

`merkle_epoch.py` calcula el root y la prueba. Pero un root que solo existe en
memoria no prueba nada: **si el verificador tiene que fiarse de quien se lo da,
no hay verificación.**

Publicarlo en un sitio que el emisor no controla es lo que convierte "confía en
mí" en "compruébalo tú".

---

## Uso

```python
from anclaje import sellar_epoch, leer_epoch, verificar_epoch_publicado

sello = sellar_epoch(pdb, "LOTE", publicar="fichero")
# {"version":"1","ns":"LOTE","epoch":1,"root":"…","n":4,"ts":…,"publicado":True}
```

Deja en la propia PDB:

| Clave | Contenido |
|---|---|
| `^AUDIT(ns, "ultimo")` | número del último epoch |
| `^AUDIT(ns, epoch, "root")` | root hex |
| `^AUDIT(ns, epoch, "n")` | número de hojas |
| `^AUDIT(ns, epoch, "ts")` | timestamp |
| `^AUDIT(ns, epoch, "version")` | versión del formato |

**La PDB se convierte en su propio libro de epochs.** Un auditor puede pedir el
epoch 3 de hace un año y compararlo con lo que le dieron.

---

## Modos de publicación

| modo | qué hace | para qué |
|---|---|---|
| `fichero` | append-only JSONL local | demos, y que el cliente tenga su registro |
| `http` | gancho con la URL (no implementado) | Rekor, bucket, gist — cada comprador pide el suyo |
| `none` | calcula y guarda, no publica | CI, pruebas |

`LUMEN_ANCLAJE_JSONL` cambia la ruta del registro.

---

## El escenario completo, verificado

`test_auditoria_completa.py` une las tres piezas en el flujo que se vendería:

```
PRODUCTOR (offline)     HUB                 AUDITOR
10 eventos en PDB   →   sella 4 epochs  →   recibe manifiesto
                        (^AUDIT + JSONL)     + pruebas
                                             verifica SIN la PDB
```

Verificado:
- los 4 epochs recalculados coinciden con los sellados
- el auditor confirma peso, geolocalización y hash de foto
- **detecta un peso de 5000 que no estaba**
- **años después, con solo el JSON del manifiesto y las pruebas, sigue
  verificando**

Ese último es el que vende: el sistema del productor puede haber desaparecido y la
prueba sigue en pie.

---

## Los tests

```bash
LUMEN_REPO=... python test_anclaje.py            # 7 comprobaciones
LUMEN_REPO=... python test_auditoria_completa.py # escenario completo
```

`test_anclaje.py`:
1. sellar deja el epoch en `^AUDIT`
2. el sello coincide con la PDB
3. **un sello manipulado se detecta**
4. el registro es append-only con epochs consecutivos
5. cada namespace numera por su cuenta
6. cambiar un dato cambia el root al resellar
7. **un sello viejo sigue valiendo para su época** (los epochs no se borran)

---

## Un bug encontrado al construirlo

`_leer_ns` (en `merkle_epoch.py`) recorría solo **el primer nivel** del árbol:
devolvía `LOTE(L1)` y `LOTE(L2)` con `value=None`, no las hojas
`LOTE(L1,"peso")`. Un root calculado sobre eso **no cubre los datos reales**.

Causa: `tool_order` opera **por nivel**. Hay que recorrer en profundidad, y
además:
- `subs=[]` da `"Need at least one subscript for $ORDER"` → hay que pasar `['']`
- iterar solo la raíz devuelve nodos intermedios, no hojas

Corregido con recorrido en profundidad. Verificado con árboles de 2 y 3 niveles.

**Es la tercera vez que `tool_order` muerde en esta sesión** (antes en
`certificado.leer_reglas`). Merece la pena tenerlo presente: devuelve **una**
clave en `value`, no una lista, y **por nivel**.

---

## Lo que esto NO hace

- **No hay anclaje externo real.** El modo `http` es un gancho. Para que la prueba
  valga contra un tercero hace falta publicar en Rekor/OpenTimestamps o una L2 —
  y eso depende de qué acepte el comprador.
- **No hay job periódico.** `sellar_epoch()` se llama a mano o desde CI; falta un
  cron que selle cada hora/día.
- **No escala a millones de claves.** `_leer_ns` recorre en profundidad con
  llamadas al MCP, una por nodo. Para una PDB grande hace falta recorrido por
  rangos en SQL, no por `$ORDER`.
- **No sustituye a una firma.** Un root prueba inclusión y orden; no prueba
  **quién** lo emitió. Eso necesita HMAC por nodo (existe) o firma asimétrica
  (no existe).
- **No hay prueba de no-inclusión.** Se prueba que un dato **está**; no que otro
  **no está**.
- **El registro JSONL no está encadenado.** Los epochs son consecutivos y sin
  huecos (verificado), pero no hay hash del sello anterior dentro del siguiente.
  Para un log de transparencia de verdad hace falta esa cadena.
