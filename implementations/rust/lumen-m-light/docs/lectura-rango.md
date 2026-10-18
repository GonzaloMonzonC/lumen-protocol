# Recorrido por rango: el anclaje escala

El `_leer_ns` original recorría el árbol con `tool_order`/`tool_get`: **una
llamada al MCP por nodo**. Un millón de claves = un millón de llamadas.

`lectura_rango.py` lo hace con **una query SQL por namespace**.

---

## La clave: el subkey es un BLOB prefijado

`encode_subkey()` produce claves donde cada subscript lleva su tipo y un `\xff`
final:

```
['L1', 'peso']  →  \x02L1\xff\x02peso\xff
```

Consecuencia: **las claves de un namespace (o de un subárbol) tienen un prefijo
común y ordenan por bytes.** Eso permite:

```sql
SELECT subkey, value FROM _globals
 WHERE ns = ? AND subkey >= ? AND subkey < ?
   AND value IS NOT NULL
 ORDER BY subkey
```

El índice `PRIMARY KEY (ns, subkey)` hace el trabajo. Es la misma idea que un
recorrido por rango en MUMPS.

### Cálculo del límite superior

```python
prefijo = encode_subkey(subs)          # \x02L1\xff
hasta   = prefijo[:-1] + bytes([prefijo[-1] + 1])   # \x02L2
```

Con acarreo si el prefijo acaba en `0xFF` (sube el byte anterior y trunca).

---

## Uso

```python
from lectura_rango import leer_ns_rango, contar_ns, listar_namespaces

leer_ns_rango(pdb, "LOTE")              # todas las hojas del ns
leer_ns_rango(pdb, "LOTE", subs=["L1"]) # solo el subárbol L1
contar_ns(pdb, "LOTE")                  # cuántas, sin traerlas
listar_namespaces(pdb)                  # todos los ns con datos
```

`epoch_de_pdb()` ya usa esta vía automáticamente, con fallback al recorrido
clásico si algo falla.

---

## Medido

| Claves | Recorrido | Merkle | Total | Ritmo |
|---|---|---|---|---|
| 100.000 | 1,38 s | 1,56 s | **2,9 s** | 34.000/s |
| **1.000.000** | — | — | **31 s** | 32.000/s |

Extrapolación del recorrido anterior con `$ORDER`: **~5 horas** para un millón.

Y lo importante: **el root es el mismo** que el del recorrido clásico (verificado
en `test_lectura_rango.py`). La optimización no cambia la prueba.

---

## Un bug encontrado al construirlo (y es sutil)

El primer intento daba **roots distintos** para el mismo namespace. La
comparación lo detectó:

```
$ORDER  →  LOTE(L1,"pais") = 'co'      ← deserializado
rango   →  LOTE(L1,"pais") = '"co"'    ← JSON crudo, con comillas
```

**La columna `value` guarda JSON sin decodificar.** `tool_get` lo deserializa; el
SQL crudo no. Sin pasar por el decodificador, el digest cambia y el root no
cuadra con el clásico.

Corregido replicando `_decode_db_value` (la misma lógica que `lumen_mlight`).

**Este es exactamente el tipo de bug que el test cruzado tenía que cazar**: una
optimización que cambia el resultado en silencio. Sin comparar contra el recorrido
clásico, habría pasado.

---

## Lo que esto NO resuelve

- **Particiones.** `_get_conn(ns)` respeta el mapeo, pero si un namespace está
  partido en varios ficheros, esta lectura ve solo uno. Habría que recorrer cada
  partición.
- **PDBs sin SQLite directo.** Si la PDB vive en otro backend, el fallback al
  recorrido por `$ORDER` funciona pero es lento.
- **Memoria.** Con un millón de claves se cargan ~1M de dicts en RAM antes de
  hashear (~300 MB). Para decenas de millones habría que hashear en streaming,
  hoja a hoja, sin acumular.
- **El Merkle sigue siendo en memoria.** Con 1M el árbol ocupa ~64 MB (dos niveles
  de hashes de 32 bytes). Para 100M habría que escribir niveles a disco.
- **No lo he probado con la PDB de producción** (29k filas). El test usa PDB
  temporales y 1M de claves sintéticas.
