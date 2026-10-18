# Anclaje: Merkle root por epoch

La **otra mitad** de la primitiva de prueba.

```
digest canónico → "esta decisión se tomó así"      (certificado, doc 15)
Merkle root     → "este dato existía el día 14"    (anclaje, doc 10)
```

Con las dos, un tercero verifica sin confiar en nadie. **Sin la segunda, un
expediente de Origen (doc `06`) no se puede auditar.**

---

## Por qué usa la misma proyección canónica

El doc `10` avisa: *"hace falta un formato canónico — la misma lección de las
subkeys"*. Si dos nodos ordenan o normalizan distinto, calculan roots distintos
para los mismos datos y el anclaje no vale.

`merkle_epoch.py` reutiliza `proyeccion()` de `digest_canonico.py`:

- misma normalización de números (12 cifras significativas)
- mismo orden
- mismos marcadores

Un registro tiene **exactamente la misma representación** en un digest de estado
y en una hoja de Merkle. Por eso `0.1+0.2` y `0.3` dan el mismo root, igual que
dan el mismo digest.

---

## Estructura

```
hoja_i = sha256("v1␞hoja␟" + linea_canonica)
nodo   = sha256("v1␞nodo␟" + min(a,b) + max(a,b))
root   = raíz
```

Dos decisiones deliberadas:

**1. `min/max` en el hash de par.** Hace el árbol **independiente del orden**:
dos nodos con los mismos datos en distinto orden dan el mismo root. Verificado.

**2. La hoja impar sube sin duplicarse.** Duplicarla es la vulnerabilidad clásica
de segunda preimagen en árboles Merkle: dos conjuntos distintos (uno con `[a,b,c]`
y otro con `[a,b,c,c]`) darían el mismo root.

---

## Uso

```python
from merkle_epoch import root_de_epoch, prueba_de_inclusion, verificar_inclusion

epoch = root_de_epoch(globals_)          # {"root", "n", "hojas", "alto"}
prueba = prueba_de_inclusion(epoch, "LOTE␟L1|peso␟1200")
verificar_inclusion(prueba, epoch["root"])   # True/False — SIN la PDB
```

La prueba es un dict serializable a JSON. Se puede guardar, enviar por email o
publicar: contiene la hoja, el camino de hermanas y el root.

---

## El caso del doc 06, de punta a punta

`test_expediente_origen.py` simula el flujo real:

```
PRODUCTOR (PDB local)        HUB (consolida)        AUDITOR
captura offline firmada  →   Merkle root del    →   verifica con la
sin red                      lote + manifiesto      prueba, SIN acceso
```

El auditor recibe **solo** el manifiesto (`{lote, root, n_eventos}`) y **una
prueba de inclusión** por dato que quiera comprobar. No necesita la PDB, ni el
sistema del productor, ni el del hub.

Verificado:
- el auditor confirma el peso y la geolocalización
- un peso falsificado (2000) no tiene prueba
- una prueba fabricada a mano no cuadra con el root
- si el productor cambia el peso después, el root cambia y el manifiesto viejo
  deja de cuadrar
- **años después, con solo dos JSON, la verificación sigue valiendo**

Ese último es el que importa: el sistema del productor puede haber desaparecido y
la prueba sigue siendo comprobable.

---

## Los tests

```bash
LUMEN_REPO=... python test_merkle_epoch.py       # 9 comprobaciones
LUMEN_REPO=... python test_expediente_origen.py  # caso 06 completo
```

`test_merkle_epoch.py`:
1. root estable con los mismos datos
2. **no** depende del orden de inserción
3. cambiar un valor cambia el root
4. prueba verificable sin la PDB
5. una prueba manipulada se detecta
6. un dato ausente no tiene prueba
7. un epoch vacío tiene root definido (se puede probar que estaba vacío)
8. misma proyección canónica que el digest de estado
9. los floats no rompen el root

---

## Lo que esto NO hace

- **No publica el root en ningún sitio.** Falta el anclaje externo (Rekor,
  OpenTimestamps o una L2). El doc `10` lo llama "el notario"; aquí está el
  cálculo y la prueba, no la publicación.
- **No hay epoch automático.** Falta un job que calcule el root cada hora/día y
  lo guarde en `^AUDIT(epoch, root)`.
- **No cubre toda la PDB.** `epoch_de_pdb()` recorre namespaces con `tool_order`,
  pero no lo he probado contra una PDB grande. Para millones de claves hace falta
  el recorrido por rangos, no el iterativo.
- **No sustituye a una firma.** Un Merkle root prueba inclusión y orden; no
  prueba **quién** lo emitió. Para eso hace falta el HMAC por nodo (que existe) o
  una firma asimétrica (que no).
- **No hay prueba de no-inclusión.** Se puede probar que un dato está; no que
  otro **no** está (eso necesita árboles ordenados o un root por rango).
