# DDP para los escenarios de los papers — qué hay, qué falta

> Estudio 2026-11-24. Responde a: **si el destino son criptomoneda, flota de
> barcos y flota aérea, ¿qué replicación hace falta y qué tenemos?**
> Todo lo marcado VERIFICADO es leído en código o ejecutado.

---

## 0 · La conclusión, primero

**El plan que propuse ayer estaba mal dimensionado.** Diseñé un sync de PDB
local↔edge, que sirve para "mi PC y mi NAS". Criptomoneda, flotas marítimas y
enjambres aéreos no piden eso: piden **replicación entre pares sin autoridad
central, con prueba criptográfica de lo que se replica**.

Y aquí está lo bueno: **ya tenéis la mitad de eso construida y no lo sabíamos.**

| Pieza | Qué prueba | Estado |
|---|---|---|
| `lumen-znet` | Transporte entre nodos | ✅ 31 tests |
| `lumen-nodo/cadena.rs` | **Completitud por cadena de hashes** (Sha-256, sellos cada 100) | ✅ **verificado, tests de manipulación** |
| `lumen-nodo/identidad.rs` | **Autoría por Ed25519 + raíz de armador jerárquica** | ✅ **142 tests en lumen-nodo** |
| `pdb_sync_engine` | Replicación local↔edge | 🔴 **roto: solo replica claves nuevas** |

**La replicación es el único eslabón que falta.** Lo demás ya está.

---

## 1 · Lo que ya está construido (VERIFICADO hoy)

### 1.1 Cadena de hashes — completitud

`implementations/rust/lumen-nodo/src/cadena.rs`, ADR-003.

```
hash_muestra = sha256( prev_hash || valor )
valor guardado = <valor>|<prev_hash>|<hash>
```

Sellos cada 100 muestras:
`sello = sha256(sello_anterior || hash_1 || … || hash_100)`

Verificar 21.600 muestras (6 h de telemetría a 1 Hz) cuesta **216 comprobaciones**
en vez de 21.600. Eso es la diferencia entre poder auditar a bordo de un barco o no.

**El doc del módulo lo dice con las palabras del caso de uso real:**
> "Un barco que pierde cobertura seis horas y luego sube 21.600 muestras necesita
> que el receptor pueda probar que están todas, en orden, sin huecos."

Tests verdes que lo demuestran: `detecta_y_localiza_una_muestra_borrada`,
`una_muestra_manipulada_en_disco_se_detecta`, `detecta_cadena_rota_por_enlace`.

### 1.2 Identidad de flota — autoría

`implementations/rust/lumen-nodo/src/identidad.rs`, ADR-003.

```
  RAÍZ DEL ARMADOR (Ed25519)
     └── firma ──▶ clave del BARCO A
                    └── firma ──▶ sus muestras, sus anuncios
```

Un barco B acepta a A si (1) la clave de A verifica lo que envía y (2) esa clave
está firmada por la raíz del armador que B ya tiene. **Sin listas de hashes y sin
autoridad remota.**

Tests verdes: `una_flota_entera_funciona_y_las_ajenas_se_rechazan`,
`un_impostor_no_puede_firmar_como_un_barco_de_la_flota`,
`cambiar_el_nombre_del_barco_en_el_certificado_lo_invalida`.

**Esto es exactamente lo que pide el paper de flota.** No hay que diseñarlo: está.

### 1.3 Lo que el ADR-003 dice que NO prueba

Y esto es tan importante como lo anterior. El ADR lo declara explícitamente:
responde a completitud, integridad, autoría y pertenencia — **y a ninguna más**.
No prueba que el dato sea *verdad* (un sensor puede mentir), ni que el nodo no
haya reescrito su propia historia antes de firmar.

---

## 2 · Lo que falta — y no es lo que yo había planeado

### 2.1 La replicación (el eslabón roto)

Confirmado con prueba ejecutada ayer: `push_full_diff` usa
`set(local) - set(edge)` → **solo replica claves nuevas**. Cambios de valor y
borrados se pierden en silencio.

### 2.2 El modelo de replicación correcto para flotas NO es local↔edge

Esto es lo que hay que cambiar de mentalidad:

| Contexto | Modelo | Por qué |
|---|---|---|
| PC ↔ NAS | local↔edge, bidireccional | Dos nodos, uno canónico |
| **Flota de barcos** | **muchos↔muchos, con cortes** | Un barco sin cobertura 6 h no puede esperar a un edge |
| **Flota aérea / enjambre** | **muchos↔muchos, efímero** | Los nodos aparecen y desaparecen |
| **Criptomoneda** | **append-only + prueba** | No se "sincroniza estado": se replica un registro |

**Un edge central es un punto único de fallo y un cuello de botella** — y en el
mar no hay conectividad garantizada. El diseño tiene que funcionar **entre pares**.

### 2.3 Lo que exige cada escenario

| Escenario | Requisito duro | ¿Lo tenemos? |
|---|---|---|
| **Flota de barcos** | Completitud tras corte largo; autoría por armador | ✅ cadena + Ed25519 |
| | Replicación entre pares sin edge | 🔴 falta |
| | Merge de series con huecos | 🟡 cadena detecta huecos; falta política |
| **Flota aérea / enjambre** | Nodos efímeros, alta rotación | 🔴 falta |
| | Orden parcial, no total | 🔴 falta |
| | Latencia baja entre pares | 🟡 lumen-znet sirve |
| **Criptomoneda** | Append-only, inmutable | 🟡 cadena da inmutabilidad |
| | **Prueba de inclusión (Merkle)** | 🔴 falta |
| | Doble gasto / unicidad | 🔴 falta |
| | Consenso (o ausencia deliberada de él) | 🔴 decisión pendiente |

---

## 3 · La decisión de fondo que hay que tomar

**¿LUMEN es una base de datos distribuida o un registro verificable?**

Son dos cosas distintas y llevan a diseños distintos:

**Opción A — Base de datos distribuida (CRDT / estado convergente)**
- Los nodos convergen al mismo estado.
- Resolución de conflictos automática (LWW, vectores de versión, CRDT).
- Bueno para: flota de barcos, sensores, telemetría.
- Coste: los conflictos son inevitables y hay que elegir política.

**Opción B — Registro verificable (append-only, tipo log/ledger)**
- No hay "estado actual": hay una secuencia de hechos firmados.
- La verdad es el conjunto de hechos, no una fila.
- Bueno para: criptomoneda, bitácora, auditoría.
- Coste: no se puede "corregir" un hecho; hay que añadir otro que lo anule.

**Mi lectura: no son excluyentes, y los papers piden las dos.**
La telemetría del barco es un registro append-only (opción B) que se consulta
como estado (opción A). Y eso ya lo tenéis resuelto con la cadena de hashes:
**cada muestra es un hecho inmutable, y el estado es la última muestra.**

Lo que faltaría es que la **replicación** trate las series como append-only en
vez de como KV que se sobrescribe hoy.

---

## 4 · Lo que propongo hacer, en orden

### Fase 0 · Decidir (sin código)
1. ¿Edge central o pares? Mi voto: **pares**, con edge opcional como espejo.
2. ¿Replicamos **hechos** (append-only) o **estado** (KV último valor)?
   Mi voto: **hechos**, porque la cadena ya está y encaja con los tres papers.
3. ¿Consenso? Mi voto: **no en el núcleo**. Un enjambre y una flota no necesitan
   consenso global; necesitan prueba. El consenso puede ser una capa opcional.

### Fase 1 · Replicación de hechos (el eslabón que falta)
4. Un hecho = muestra firmada con `(nodo, serie, seq, valor, prev_hash, firma)`.
5. Replicación: "dame los hechos de la serie X desde seq N".
6. Verificación al recibir: cadena + firma + pertenencia a flota.
7. Idempotencia: reenviar el mismo hecho no duplica.

### Fase 2 · Estado derivado
8. El KV actual se **deriva** de los hechos (última muestra por clave).
9. Así el sync de PDB deja de ser la fuente de verdad y pasa a ser una vista.

### Fase 3 · Lo específico de cada paper
10. Merkle por bloque para prueba de inclusión (criptomoneda).
11. Orden parcial y ventanas cortas (enjambre aéreo).
12. Compactación y retención (barco con meses de datos).

---

## 5 · Lo que NO haría

- **No arreglaría `pdb_sync_engine` como está.** Si el modelo pasa a hechos
  replicados, ese código cambia de papel: pasa a ser la *vista* derivada, no el
  mecanismo de sincronización.
- **No metería consenso en el núcleo.** Añade complejidad y latencia para un
  problema (doble gasto) que es de la capa de aplicación, no del transporte.
- **No tocaría `lumen-znet`**: 31 tests verdes y hace lo que debe.
- **No implementaría CRDT completo**: la cadena ya da el orden por serie.

---

## 6 · Preguntas abiertas para Gonzalo

1. **¿Edge central o pares?** Cambia todo lo demás.
2. **¿Replicamos hechos o estado?** Mi voto: hechos.
3. **¿La criptomoneda comparte el mismo mecanismo** o es un producto aparte?
4. **¿Qué es lo primero que quieres poder demostrar?** Un barco con 6 h de corte
   que sube todo y se verifica, o un enjambre de drones intercambiando estado.
5. **¿Cuántos nodos por flota?** 10 barcos es un problema; 10.000 drones es otro.
