# RAM del hub — medida, y la conclusión no era la esperada

> 2026-11-24. Se investigó la RAM del hub antes de buscar el techo de barcos,
> porque el caso del paper (40 × 21.600) parecía condenado.
> **Conclusión: no hay fuga. La RAM es de LMDB, y es correcta.**

---

## 1 · La sospecha inicial

El hub acumulaba los hechos en un `Vec` por conexión y los guardaba al final.
Con 864.000 hechos (40 barcos × 21.600) serían cientos de MB en RAM **que no
hacen falta**, porque los hechos van a LMDB de todos modos.

Era una sospecha razonable. Y **era falsa a medias**.

## 2 · Lo que se midió

| Barcos | Muestras | Hechos | Aceptados | RAM pico | KB/hecho |
|---:|---:|---:|---:|---:|---:|
| 5 | 6.000 | 30.000 | 30.000 | 21,3 MB | 0,73 |
| 10 | 6.000 | 60.000 | 60.000 | 30,8 MB | 0,53 |
| 20 | 6.000 | 120.000 | 120.000 | 56,3 MB | 0,48 |
| 20 | 12.000 | 240.000 | 177.709 | 96,6 MB | 0,41 |
| 40 | 2.000 | 80.000 | 80.000 | 44,9 MB | 0,58 |
| 40 | 6.000 | 240.000 | 204.072 | 90,4 MB | 0,39 |

La tasa **baja** al subir el volumen (0,73 → 0,39 KB/hecho). Eso es lo contrario
de una fuga: una fuga mantiene o sube la tasa.

## 3 · La prueba que zanjó el asunto

**Mismos 120.000 hechos, repartidos distinto:**

| Reparto | Hechos | RAM |
|---|---:|---:|
| 2 barcos × 60.000 | 120.000 | **47,5 MB** |
| 20 barcos × 6.000 | 120.000 | **56,4 MB** |

Solo **9 MB de diferencia por 18 conexiones más** — unos 0,5 MB por conexión.
Si los hechos se acumularan en RAM, los dos casos pesarían lo mismo. No pesan lo
mismo por los hechos, sino por las **conexiones**.

## 4 · La conclusión

**La RAM del hub es el caché de páginas de LMDB.**

- 120.000 hechos × ~470 B de valor real ≈ **56 MB de datos**.
- Medido: **47–56 MB**. Coincide con los **bytes escritos**, no con el número de
  hechos acumulados.
- LMDB cachea en RAM las páginas que escribe. Es su comportamiento normal, y
  **esa memoria es reclamable** por el sistema (es mmap limpio, no heap anónimo).

Y una comprobación del código que lo confirma: `MemoryHost::set` con LMDB
**no guarda en el mapa de RAM** salvo para `^SYSINFO`. El BTreeMap en memoria
solo se usa cuando no hay LMDB detrás.

## 5 · Qué se cambió igualmente

Aunque no había fuga, el diseño anterior (acumular y guardar al final) **sí era
frágil**: dependía de que cada conexión mandara poco. Se pasó a **streaming por
canal**: el hilo de red recibe y manda lotes; el hilo principal guarda y suelta.

**Se intentó drenar los canales durante la aceptación** y empeoró: bloqueaba el
bucle de `accept` y los barcos se agotaban (18.000 de 120.000). Se revirtió.

El streaming por canal se mantiene porque el diseño es mejor, aunque la medición
demuestre que la RAM no venía de ahí.

## 6 · Lo que esto significa para el paper

**40 barcos × 21.600 muestras = 864.000 hechos.**

| Componente | RAM estimada |
|---|---:|
| Datos en LMDB (caché de páginas) | ~400 MB |
| Conexiones (40 × 0,5 MB) | ~20 MB |
| **Total** | **~420 MB** |

Cabe en cualquier máquina moderna. **Y en una Raspberry Pi con 4 GB, también.**

El problema que se temía — el hub muriendo por RAM — **no existe**. Lo que había
era una arquitectura mejorable, no un fallo.

## 7 · Lo que sí es un problema real: el techo de 20-40 barcos

En las mediciones aparece un patrón que **no es de RAM y sí hay que resolver**:

| Caso | Aceptados | Rechazados |
|---|---:|---:|
| 20 × 6.000 | 120.000 | **0** |
| 20 × 12.000 | 177.709 | **62.291** |
| 40 × 6.000 | 204.072 | **35.928** |

A partir de cierto volumen por barco **se pierden hechos**, y el hub no los
rechaza por mala firma: se cortan por el temporizador de inactividad (3 s).

**Es un límite de la simulación, no del protocolo**, pero apunta a algo real:
el hub necesita **control de flujo** (decirle al barco "espera, que voy lleno")
en vez de depender de que el barco mande rápido.

## 8 · Lo que queda

1. **Control de flujo en la replicación.** El ACK actual es de fin de envío;
   hace falta un ACK intermedio o una ventana, para que el barco no sature.
2. **Buscar el techo real** (100, 500 barcos) ahora que se sabe que la RAM no
   es el límite.
3. **El temporizador de 3 s** es una tirita: con volumen alto, el hub debe seguir
   leyendo mientras tenga datos, sin cortar por silencio.
