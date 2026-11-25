# Split-brain — diseño

> 2026-11-24. Consultados Poli (2 pasadas) y Smith (multi-dominio).
> **Estado: diseñado, no implementado.**

---

## 1 · El bug, verificado

Dos escritores con la misma identidad de nodo producen hechos que colisionan:

```
hechos enviados:  6
hechos guardados: 3
DESCARTADOS EN SILENCIO: 3
```

Sin error, sin log, sin conflicto detectado. **Es la tercera vez que aparece el
mismo patrón** (sync de PDB, sello de bloque, y ahora esto): *pérdida silenciosa
donde el sistema dice que todo fue bien*.

**La causa no es la colisión. Es el descarte silencioso.** Poli lo dijo dos veces
con palabras distintas y tiene razón: una colisión es un hecho del mundo; lo
inaceptable es que nadie se entere.

## 2 · Los dos casos que hay que distinguir

| Caso | Qué pasa | Arreglo |
|---|---|---|
| **a) Reinstalación** | Un nodo se reinstala y vuelve con `seq=0`. Su historia choca con la anterior | `instance_id` nuevo + epoch que sube, con prueba |
| **b) Partición** | Dos hubs aceptan escrituras del mismo barco. Ambos emiten `seq` | Dos ramas con epoch válido → **conflicto explícito** |

Son distintos y **no se pueden tratar igual**: en (a) hay una historia buena y
una vieja; en (b) hay dos historias simultáneas y ninguna es "la buena".

## 3 · Las cuatro piezas del diseño

### 3.1 `instance_id` firmado dentro del hecho

El hecho pasa a llevar:

```
(nodo, serie, seq, instance_id, epoch, valor, prev_hash)
```

- `nodo` = **identidad de barco** (autorización: la clave del certificado).
- `instance_id` = qué **proceso** escribió (UUID al arrancar).
- `epoch` = número de era, sube en reinstalación.

El `instance_id` **no crea serie nueva**: la serie sigue siendo del barco; solo
desambigua dos escritores del mismo barco.

### 3.2 Versionado del formato — lo que Smith vio y nosotros no

**Añadir `instance_id` al cuerpo firmado rompe las firmas ya escritas.** Los
hechos existentes no lo cubren y dejarían de verificar.

Solución: **versión en el propio hecho**.

```
v: 1  -> payload canónico sin instance_id ni epoch   (hechos antiguos)
v: 2  -> payload canónico con instance_id y epoch
```

El verificador elige según `v`. **No se re-firman los v1**: eso rompería la
inmutabilidad, que es el punto del sistema.

### 3.3 Epoch con cadena de custodia

- Lo emite **el barco**, con su propia clave.
- **"Un salto requiere la firma del epoch anterior"**. Así no basta con tener la
  clave: hay que demostrar continuidad.
- Un nodo offline un mes **no queda fuera**: produce hechos con su epoch viejo,
  y eso es un **conflicto explícito**, no una exclusión.

**El agujero que queda y hay que decidirlo:** si se pierde la clave, no se puede
saltar de epoch. Sin consenso, eso es una decisión de operador. Haría falta un
**epoch de recuperación firmado por la raíz del armador**. Hoy la raíz de armador
**no está pensada para eso**: firma certificados, no recuperaciones. Es una pieza
que habría que añadir si se quiere cubrir el caso de clave perdida.

### 3.4 Nunca descartar

**La regla central**, y la que arregla el bug:

> Si `(nodo, serie, seq)` ya existe **con el mismo hash** → duplicado, se ignora
> (idempotencia).
> Si existe **con hash distinto** → **CONFLICTO**: se guardan las dos y se marca.

La rama ganadora **no la decide el almacenamiento**: es política del perfil.
Smith insiste en esto y es correcto — si la decisión vive en el storage, se
congela y no se puede cambiar sin migrar datos.

## 4 · Estructura de almacenamiento

Con dos ramas hay que cambiar la clave:

```
^HECHOS(nodo, serie, seq, instance_id) = <hecho>
^RAMAS(nodo, serie)                    = {ramas: [...], head_elegido: ...}
```

- La clave lleva `instance_id` para que dos ramas **coexistan**.
- `head_elegido` es **metadato aparte**, no parte del hecho: así se puede cambiar
  la política sin tocar los datos.
- **Coste:** hay que revisar **cada `get()`** que hoy asume unicidad
  `(nodo, serie, seq)`. Son 183 tests y varios puntos de lectura. Smith avisa de
  que el error probable es "arreglar" los tests relajando asserts en vez de
  revisar la semántica.

## 5 · Detección y operación

**Métrica obligatoria:** `descartes_por_colision` debe ser **siempre 0**. Si sube,
hay un bug, no una situación normal.

**Evento `CONFLICTO`** con: nodo, serie, seq, **los dos hashes y las dos firmas**,
y los dos `instance_id` + `epoch`.

**Cómo distingue el operador** (Smith, dominio operación):
- **Reinstalación legítima:** epoch con cadena de firmas válida hasta la raíz.
- **Partición:** dos ramas con epoch válido y **contemporáneo**, sin firma de
  revocación.

Sin el campo *"quién revocó a quién y cuándo"*, el operador no puede
distinguirlos. El log tiene que llevar la evidencia criptográfica, no una
narrativa.

## 6 · Lo que NO se hace (coinciden Poli y Smith)

- ❌ **Consenso en el núcleo.** El paper no lo pide. Una flota necesita prueba,
  no acuerdo global.
- ❌ **"El epoch más alto gana" a secas.** Sin cadena de custodia, cualquiera con
  la clave gana siempre.
- ❌ **Rechazar una rama.** Rechazar es la pérdida silenciosa que ya tenemos.
- ❌ **Borrar la rama perdedora.** Se marca; que decida quien opera.
- ❌ **Usar el reloj para LWW.** Relojes sesgados.
- ❌ **Meter `instance_id` como parte de la serie.** Crearía series huérfanas.

## 7 · Orden de implementación

1. **Formato v2 con versión** y el verificador eligiendo payload. Sin esto, todo
   lo demás rompe hechos existentes. *(Smith)*
2. **`instance_id` + `epoch` firmados** dentro del hecho v2.
3. **Clave con `instance_id`** y `head_elegido` como metadato aparte.
4. **Nunca descartar**: conflicto explícito + evento con evidencia.
5. **Métrica `descartes_por_colision`** y test que exija 0.
6. **Epoch con cadena de custodia** (salto firmado por el anterior).

## 8 · Lo que queda abierto

1. **Epoch de recuperación con clave perdida.** Sin consenso es decisión de
   operador, y hoy la raíz de armador no está pensada para firmarlo. **Hay que
   decidir si se añade.**
2. **Resolución de la rama buena.** El diseño deja el hueco de forma explícita:
   es política de perfil (`conflicto`), y hoy solo hay `ultimo_gana`,
   `primero_gana` y `manual`. Ninguna sabe de ramas: hay que añadir
   `por_epoch` y `por_rama` (que decida el operador).
3. **Compactación con dos ramas.** La regla "no borrar el último hecho de la
   serie" hay que extenderla: **tampoco se puede borrar el último de cada rama**.
