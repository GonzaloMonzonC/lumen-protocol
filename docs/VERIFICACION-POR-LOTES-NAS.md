# Verificación por lotes en la NAS — y por qué los sellos la hacen innecesaria

> 2026-11-24. Medido en la NAS (ARMv7, 1 núcleo). Responde la pregunta: ¿sirve
> trocear la verificación para que un nodo pequeño siga siendo útil?

---

## 1 · La pregunta

Verificar 21.600 hechos de golpe bloquea el nodo **75 s**. Durante ese tiempo no
atiende nada más.

¿Trocear en lotes reduce el bloqueo, aunque el total sea el mismo?

## 2 · La respuesta: el total no baja, el bloqueo sí

Verificando **cada firma** (21.600 hechos, 21600 firmas Ed25519):

| Lote | Total | Lotes | **Bloqueo por lote** |
|---:|---:|---:|---:|
| **64** | 75.919 ms | 338 | **224 ms** |
| 256 | 78.243 ms | 85 | 920 ms |
| 1.024 | 76.227 ms | 22 | 3.464 ms |
| 4.096 | 75.171 ms | 6 | 12.528 ms |
| **21.600 (todo)** | 75.352 ms | 1 | **75.352 ms** |

- **El total no cambia**: 75–78 s en todos los casos. Trocear no ahorra trabajo.
- **El bloqueo máximo cae en picado**: de **75 s a 224 ms** con lotes de 64.

224 ms es un bloqueo tolerable: el nodo puede atender peticiones entre lote y
lote. 75 s no lo es.

## 3 · Pero los sellos lo resuelven mejor

La misma serie, **verificando sellos de bloque** en vez de cada firma:

```
sellos 21.600 hechos -> 1.662 ms total (216 sellos)
```

| Estrategia | Bloqueo máximo | CPU total |
|---|---:|---:|
| Firma individual, todo | **75 s** | 75 s |
| Firma individual, lotes de 64 | 224 ms | 76 s |
| **Sellos (bloque 100)** | **1,7 s** | **1,7 s** |
| Sellos + lotes de 64 | ~10 ms | 1,7 s |

**Los sellos son 45× más rápidos en total**, y su bloqueo único de 1,7 s ya es
aceptable sin trocear nada.

## 4 · La conclusión

**La verificación por lotes no salva la firma individual: solo la hace
tolerable.** Sigue consumiendo 76 s de CPU por cada ronda de 21.600 hechos, y en
un nodo de 1 núcleo eso es el nodo entero ocupado.

**Los sellos hacen la pregunta innecesaria**: 1,7 s de bloqueo único es algo que
un nodo puede permitirse.

**Orden de preferencia:**

1. **Sellos de bloque** (lo que ya hace el perfil de barco). 1,7 s.
2. **Sellos + lotes**, solo si hay picos que exigen bloqueos de milisegundos.
3. **Firma individual troceada**, únicamente si por alguna razón no puede haber
   sellos.
4. **Firma individual de golpe**: descartado. 75 s de nodo bloqueado.

## 5 · Dónde sí hace falta el troceado

Con sellos, el troceado sigue teniendo un uso: **no bloquear 1,7 s de una vez**
cuando el nodo tiene tráfico interactivo. Lotes de 16 bloques dejan bloqueos de
~100 ms, que es lo que ya hace el `Escritor` con la durabilidad.

Es la misma idea que el lote de commits en LMDB: **trocear no acelera, mejora la
latencia**.

## 6 · Lo que esto confirma del diseño

| Decisión tomada antes | Confirmada por |
|---|---|
| Perfil de barco: `firma: por_bloque` | 45× menos CPU en el hub |
| `durabilidad: lote` en el perfil | Misma lógica: trocear mejora latencia |
| Perfiles: la firma es configurable | Un ledger que no use sellos pagaría 45× |

**Dos decisiones independientes resultaron ser la misma idea:** agrupar antes de
pagar el coste caro (fsync, o firma).

## 7 · Lo que no se ha medido

- **Sellos + lotes de tamaños distintos** en la NAS (se calculó, no se midió).
- **Con el nodo atendiendo tráfico real** a la vez: aquí se mide aislamiento.
- **Raspberry Pi 4/5**, que tiene criptografía por hardware y 4 núcleos. Allí la
  firma individual sería mucho más barata y quizá la conclusión cambie.
