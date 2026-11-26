# Prueba de inclusión (Merkle) — demostrar un hecho sin entregar el registro

> 2026-11-26. Última pieza que faltaba para el escenario de criptomoneda.
> Código: `lumen-nodo/src/merkle.rs`

---

## 1 · El problema que resuelve

La cadena de hashes prueba **completitud**: que no falta ningún hecho. Pero para
comprobarlo hay que tener **la serie entera**.

- Un barco con 21.600 hechos: viable.
- Un ledger con un millón de hechos: **no**.

Merkle añade **prueba de inclusión**: demostrar que UN hecho está en el registro
**sin entregar el registro**.

## 2 · Medido con los hechos reales del barco

```
21.600 hechos firmados y encadenados:
  árbol construido en      1,17 s
  prueba generada:         15 hashes = 975 bytes
  serie completa sería     1.382.400 bytes
  AHORRO:                  1417x
  la prueba verifica en    676 µs
```

**Demostrar que el hecho 12.345 está en el registro cuesta 975 bytes en vez de
1,38 MB.** Y se verifica en menos de un milisegundo.

## 3 · Es logarítmico, no lineal

| Hechos | Tamaño de la prueba |
|---:|---:|
| 100 | ~7 hashes (~455 B) |
| 21.600 | **15 hashes (975 B)** |
| 1.000.000 | ~20 hashes (~1,3 KB) |

El doble de hechos suma **un hash** a la prueba. Esa es la propiedad que hace
viable un ledger: la prueba no crece con el registro.

## 4 · Lo que se comprobó que NO se puede hacer

| Ataque | Resultado |
|---|---|
| Cambiar el hecho y probarlo | ❌ no verifica |
| Cambiar un hash hermano del camino | ❌ no verifica |
| Borrar un hecho del medio | ❌ la raíz cambia |
| Probar un hecho posterior contra la raíz original | ❌ no verifica |
| Reordenar la serie | ❌ raíz distinta |
| Usar una prueba de otro árbol | ❌ no vale |
| Índice fuera de rango | no da prueba |

## 5 · Una decisión de seguridad que conviene explicar

**Con número impar de nodos, el último sube tal cual. NO se duplica.**

Bitcoin sí duplica el último nodo, y eso permitió el **CVE-2012-2459**: dos
conjuntos distintos de transacciones producían la **misma raíz**, así que un
atacante podía colar un bloque distinto que validaba igual.

Esta implementación no duplica, y hay un test que lo demuestra: 5 hojas y
5+duplicado dan raíces **distintas**.

También se usa un **separador `\x1f`** entre los dos hijos de un nodo interno.
Sin él, `hash("ab" + "c")` y `hash("a" + "bc")` colisionarían.

## 6 · Lo que Merkle NO prueba

Esto importa tanto como lo que sí prueba. **Merkle prueba inclusión, no autoría.**

| Pregunta | Quién la responde |
|---|---|
| ¿Falta algún hecho? | Cadena de hashes |
| **¿Está este hecho concreto?** | **Merkle, sin dar todo** |
| ¿Lo firmó quien dice? | Ed25519 |
| ¿La clave es de mi flota? | Certificado contra la raíz del armador |
| ¿Reconstruyeron la historia desde cero? | Custodia de epoch |

**Cinco comprobaciones distintas.** Ninguna sustituye a las otras.

## 7 · Estado del escenario criptomoneda

| Requisito | Estado |
|---|---|
| Append-only inmutable | ✅ |
| Doble gasto (detección por recurso) | ✅ |
| **Prueba de inclusión** | ✅ **ahora** |
| Consenso | 🔵 no en el núcleo (decisión tomada) |

**No queda ningún requisito técnico pendiente** de los que el estudio de
escenarios marcaba para criptomoneda.

## 8 · Por el cable (cerrado)

La prueba se pide y se devuelve por DDP con dos mensajes, otra vez con prefijo
dentro de `DATA` para no tocar los cinco tipos fijados en la spec:

```
PETICIÓN    PROOF|<serie>|<seq>
RESPUESTA   PROOFR|<raiz>|<indice>|<total>|<hoja>|<h>:<0|1>,...
```

El `0`/`1` de cada hermano dice si va a la izquierda o a la derecha: sin eso la
prueba no se puede recomponer.

**Medido de punta a punta** (`tests/merkle_cable.rs`):

| | |
|---|---:|
| Petición | **16 bytes** |
| Respuesta para 300 hechos | **747 bytes** (9 hashes) |
| Respuesta para 5.000 hechos | **1.017 bytes** |
| Serie completa de 5.000 por el cable | **1.107.716 bytes** |
| **Ahorro** | **1089×** |

Y el verificador **no recibe los hechos**: solo los 9 hashes del camino.

Comprobado también que una prueba **manipulada en el cable** no verifica, ni
cambiando la hoja ni cambiando un hermano del camino.

El árbol se construye ahora desde el **store real** (`hechos_store::arbol_de_serie`
y `prueba_de_hecho`), no desde hashes sueltos.

## 9 · Lo que sigue pendiente

- **Raíz publicada**: para que sirva de algo, la raíz tiene que estar en un sitio
  que el verificador no controle. Si la sirve el mismo nodo, la prueba solo vale
  contra ese nodo — que es lo que ya garantizaba la firma.
- **Persistir el árbol**: hoy se reconstruye desde la serie. Para 21.600 hechos
  tarda 1,17 s (aceptable); con un millón habría que construirlo por bloques.
