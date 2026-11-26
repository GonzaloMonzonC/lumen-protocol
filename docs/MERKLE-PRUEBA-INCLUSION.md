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

## 8 · Lo que falta para que esto sea un producto

Nada de lo anterior resuelve el negocio. Lo que sigue pendiente:

- **Prueba de inclusión por red**: hoy se genera en memoria. Falta un mensaje
  DDP que la pida y la devuelva.
- **Raíz publicada**: para que sirva de algo, la raíz tiene que estar en un sitio
  que el verificador no controle (un bloque, un periódico, otro nodo).
- **Estado en la PDB**: hoy el árbol se construye desde la serie. Con un millón
  de hechos hay que persistirlo o construirlo por bloques.
