# RAG en M-Light: de TF-IDF a búsqueda vectorial

> Estado: implementado y verificado el 21-nov-2026. Commit `287c1edf`.
> Devuelve resultados medidos, no estimaciones.

## Qué había y qué falta

La M-Light traía `$DEVICE("rag:query")`, un TF-IDF léxico sobre el global
`^RAG("doc",id,"texto")`. Funciona bien cuando la pregunta usa **las mismas
palabras** que el documento. Falla cuando no.

El caso que lo destapó, real, del Manual de Mesas Electorales:

| Pregunta del ciudadano | Lo que dice el manual | Qué devolvía TF-IDF |
|---|---|---|
| «¿Puedo votar con el **DNI caducado**?» | «Se aceptará la presentación de estos documentos **aunque estén caducados**» | un formulario de inscripción, score 0,12 |

Cero palabras en común entre «DNI caducado» y «documento de identidad en vigor»,
salvo «caduc-». TF-IDF cuenta palabras iguales, no significados.

**`rag:embed` añade búsqueda por significado sin meter un modelo en el motor.**

## La decisión de diseño: los vectores son DATOS, no código

El motor corre en WASM y en nodos de 32 bits. Un modelo de embeddings ocupa
120-470 MB y no cabe — ni en el intérprete ni en la memoria de esos nodos.

Por eso los vectores **se calculan fuera** y se cargan en la misma global que
los textos:

```
^RAG("doc",id,"texto")        el trozo (como siempre)
^RAG("doc",id,"vec")          el vector, coma-separado, normalizado L2
^RAG("qvec",sha1(pregunta))   el vector de la pregunta, precargado por quien llama
```

El motor solo hace **producto escalar**. Como los dos vectores están
normalizados L2, el producto escalar **es** el coseno. Un motor de 1,2 MB hace
búsqueda semántica con 384 dimensiones.

Esto mantiene tres propiedades que importan:

1. **El motor sigue siendo autónomo**: no depende de Python, ni de red, ni de GPU.
2. **Determinista**: mismos datos, mismo resultado, siempre.
3. **Portable**: cabe donde ya cabía. Nodos de 32 bits incluidos.

## API

```m
; búsqueda vectorial. La pregunta llega por sha1 porque el motor no puede
; calcular embeddings: quien llama vectoriza, guarda en ^RAG("qvec",hash) y
; pide la búsqueda por ese hash.
$DEVICE("rag:embed","<sha1>",[ns="RAG"],[k=4],[filtro])

; cuántos vectores hay y de qué dimensión
$DEVICE("rag:embed:stats",[ns="RAG"])   → "vecs=341;dim=384"
```

**El filtro funciona igual que en `rag:query`**: prefijos de id separados por
`|`. Eso permite tener dos corpus en el mismo motor sin que se contaminen:

```m
$DEVICE("rag:embed","abc123","RAG",4,"mesa-")      ; solo el manual de mesas
$DEVICE("rag:embed","abc123","RAG",4,"altcamp-")   ; solo datos municipales
```

### Ejemplo completo

```m
; 1. cargar (una vez)
S ^RAG("doc","mesa-080","texto")="Se aceptará la presentación de estos documentos aunque estén caducados"
S ^RAG("doc","mesa-080","vec")="0.027,-0.011,0.094,..."
S ^RAG("qvec","a1b2c3")="0.033,-0.008,0.101,..."

; 2. consultar
W $DEVICE("rag:embed","a1b2c3","RAG",3,"mesa-")
; → — [mesa-080] (s=0.812) Se aceptará la presentación de estos documentos…
```

## Lo que se midió

### 1. El troceado pesa más que el modelo

Antes de tocar vectores se midió el troceado. Un estudio del 2026 sobre 36
estrategias en 6 dominios encontró que **el agrupado por párrafo es lo que
mejor funciona en texto legal**, y que trocear por caracteres da una precisión
@1 de solo 2-3 %.

Trocear por **proposición** (una regla = un trozo, ~200 caracteres) subió el
acierto de TF-IDF **del 20 % al 44 %** — sin cambiar el motor ni el modelo.

### 2. Separación dentro / fuera de dominio

25 preguntas legítimas, 15 fuera de dominio («¿cómo se hace una paella?»).
Lo que importa no es acertar, es **poder abstenerse**: en un dominio con
consecuencias legales, responder mal es peor que decir «no lo sé».

| Recuperador | Ratio dentro/fuera | Umbral | Cubre |
|---|---|---|---|
| TF-IDF solo | 1,45× | 0,551 | 14/25 |
| Embeddings solos | 2,06× | 0,408 | 21/25 |
| **Híbrido (RRF)** | **2,17×** | **0,400** | **23/25** |

TF-IDF nunca alcanza el 1,5× de separación. Los vectores sí. **Las dos piezas
son necesarias**: el troceado es el problema principal, los embeddings son los
que permiten distinguir «paella» de «papeleta».

### 3. La asimetría de vectorización empeora el resultado

Primera versión: los documentos se vectorizaban con un prefijo
(`"Identificación de votantes · página 9. texto"`) y la pregunta se vectorizaba
cruda. Medido:

| | Acierto top-3 | Margen top1-top2 |
|---|---|---|
| Con prefijo de sección | 66 % | 0,034 |
| **Solo texto** | **75 %** | **0,044** |

El prefijo **metía ruido** en el vector en vez de dar contexto. Se quitó.

### 4. La ventana de vecinos

Un tema se parte en varios trozos contiguos y el ganador suele ser el **vecino**
del bueno. Devolver el ganador y sus contiguos:

| Ventana | Acierto top-1 |
|---|---|
| Solo top-1 | 52 % |
| +1 vecino | 60 % |
| +2 vecinos | 64 % |

Gratis: no toca modelo ni motor.

## Resultado final, con el manual real

| Pregunta | Score | Trozo |
|---|---|---|
| ¿Se abre el sobre del voto por correo? | **0,832** | «Voto por correo. Acto seguido…» p11 |
| ¿Qué es un voto nulo? | **0,734** | «Son VOTOS NULOS:…» p13 |
| ¿Quién me ayuda si no sé leer? | **0,526** | «Si una persona no sabe leer…» p10 |
| ¿Cuánto se cobra? | **0,400** | «Dieta de 75 €» p4 |
| ¿Quién ganó el mundial? | 0,332 | **se abstiene** |
| ¿Cómo se hace una paella? | 0,397 | **se abstiene** |

## Cómo se usa desde fuera del motor

El motor no sabe calcular embeddings, así que el reparto es:

```
navegador → portero (Worker)      token secreto, rate limit, caché
          → proxy               vectoriza la pregunta si no llega qvec
          → servicio de vectores  fastembed + MiniLM multilingüe (384 dims)
          → M-Light             $DEVICE("rag:embed") → coseno → párrafo
```

- **El navegador solo manda texto.** No descarga ningún modelo.
- **El vectorizador es un servicio aparte** (fastembed + onnxruntime, ~120 MB):
  meterlo en el motor o en el proxy engordaría una imagen que no lo necesita.
- **El motor recibe el vector en `^RAG("qvec",hash)`** y trabaja con el coseno.

En una MVM **nativa** (Linux) el vectorizador puede vivir en el mismo proceso,
y entonces el servicio aparte desaparece. Ver `docs/RAG-MVM-NATIVA.md`.

## Diferencias entre la API WASM y la API C

Al portar la búsqueda a una MVM nativa aparecieron dos diferencias que cuestan
horas si no se saben:

| | WASM (`pkg/lumen_mlight.js`) | Nativa (`liblumen_mlight.so`) |
|---|---|---|
| Llamada | `m_compile(src)` → `m_execute_raw(compiled, globals_json)` | `lm_compile_json(src)` → `lm_execute_json(request_json)` |
| **Salida del `W`** | `{"output": "..."}` en la raíz | **`{"state": {"output": "..."}}`** |
| Globals | se pasan y se recogen igual | igual |
| Estado | sin estado: hay que pasar los globals en cada llamada | igual |

**Las dos son sin estado.** Los globals cargados en una llamada **no existen**
en la siguiente; hay que pasarlos en cada petición y quedarse con los que
devuelve. Se midió: `stats` devolvía `vecs=0` hasta que se pasaron los globals.

## Cómo se calculan los vectores

```python
from fastembed import TextEmbedding
import numpy as np

model = TextEmbedding("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
V = np.array(list(model.embed(textos)))
V = V / np.linalg.norm(V, axis=1, keepdims=True)      # L2 → coseno por producto escalar
# guardar cada fila como "0.027,-0.011,0.094,..." en ^RAG("doc",id,"vec")
```

**Modelo elegido**: `paraphrase-multilingual-MiniLM-L12-v2` (384 dims, 220 MB,
CPU). Alternativas evaluadas:

- `intfloat/multilingual-e5-small` — no está soportado por `fastembed` 0.8; la
  que sí está es `e5-large`, de 2,24 GB, desproporcionada para 341 trozos.
- `all-MiniLM-L6-v2` — **no usar**: solo inglés.

## Lo que no hace

- **No genera texto.** Devuelve el párrafo literal. Generar una respuesta con
  un LLM exige además un validador que compruebe que la cita es substring real
  del documento; sin eso, el modelo parafrasea y altera plazos y cifras.
- **No filtra por umbral en el motor.** El motor devuelve los k mejores con su
  score; el umbral lo aplica quien llama, porque depende del corpus.

---

# Cómo montar un RAG sobre un manual: las tres decisiones que importan

Guía práctica, con las cifras medidas sobre el Manual de Mesas Electorales
(37 páginas, 235 trozos, 49 preguntas de evaluación). Si vas a montar un RAG
sobre un documento normativo, estas son las tres palancas y el orden en que
mueven el resultado.

## 1. El troceado pesa más que el modelo

Antes de elegir modelo, trocea bien. Sobre el mismo motor y el mismo
recuperador, cambiar solo el troceado movió el acierto top-1 del **20 % al
44 %**.

Lo que funciona:

- **Una unidad de sentido = un trozo.** Una regla, un requisito, un paso. Si el
  texto trae una lista («solicitarán cualquiera de estos documentos: DNI,
  pasaporte, carné»), la lista va **entera** con su frase introductoria. Cortar
  una lista por la mitad produce trozos que empiezan a media idea y ningún
  vector sabe de qué hablan.
- **150-400 caracteres por trozo.** Suficiente contexto para que el vector
  capture el tema, corto para que no lo diluya.
- **Trozos con nombre.** Anteponer al texto un campo `tema` escrito con las
  palabras que usaría quien pregunta —no con el título del documento— mejora
  el emparejamiento. El índice no dice «Identificación de votantes»; dice
  «DNI caducado fotocopia carné conducir pasaporte». Es el puente entre el
  vocabulario del que pregunta y el del que redactó la norma.
- **Descartar portada, índice y formularios.** Repiten todo el vocabulario y
  ganan siempre en cualquier búsqueda léxica.

Un LLM ayuda a trocear y a poner esos temas: es rápido, barato y respeta los
límites de las ideas mejor que una regla. **Con una condición**: cada trozo
devuelto se verifica como **substring literal** del original. Si parafrasea, se
descarta. Sin esa puerta, entra texto inventado en el corpus de un documento
oficial.

## 2. El modelo se elige por idioma y por tarea, no por tamaño

Sobre el mismo corpus y el mismo troceado, medido con 49 preguntas:

| Modelo | Dims | Tamaño | Acierto top-3 |
|---|---|---|---|
| Genérico multilingüe pequeño | 384 | 220 MB | 70 % |
| Genérico inglés grande | 1024 | 640 MB | 70 % |
| **Especializado en español** | **768** | **640 MB** | **85 %** |

**Cuatro veces más dimensiones no aportó nada** (el de 1024 dims empató con el
de 384). El que ganó fue el **especializado en el idioma del documento**.

Regla: si el corpus está en español, el modelo de embeddings también. El tamaño
importa menos de lo que sugiere el marketing; el idioma y el entrenamiento para
recuperación, mucho más.

## 3. Calibra el umbral con un set etiquetado

Sin umbral, el sistema responde a todo. Con umbral mal puesto, responde mal o
se calla de más. El umbral **no se elige a ojo**: se calibra.

**El método:**

1. Escribe **34 preguntas legítimas** y **15 fuera de dominio**. Las de fuera no
   son absurdas: son preguntas que alguien haría por error (otra
   administración, otro trámite, otra materia).
2. Anota a mano, para cada legítima, un fragmento que **debe** aparecer en el
   trozo ganador. Se cuenta como acierto solo si aparece.
3. Barre el umbral y, para cada valor, cuenta: cuántas preguntas legítimas
   responde, y **cuántas de fuera responde también** (falsos positivos).
4. Elige por **utilidad**, no por F1: `aciertos − 5 × falsos_positivos`.

**Por qué el 5.** Un falso negativo molesta. Un falso positivo en un dominio
normativo se **ejecuta**: alguien actúa según una respuesta equivocada. Pesa
más.

**Curva típica** (mismo sistema, distintos umbrales):

| Umbral | Responde | Acierta de las que responde | Falsos+ |
|---|---|---|---|
| bajo | 34/34 | 91 % | 4 |
| medio | 31/34 | 90 % | 2 |
| alto | 20/34 | 95 % | 1 |
| muy alto | 18/34 | 94 % | 0 |

No hay un ganador único: **hay una elección de producto**. Cobertura o
precisión. Se decide sabiendo el coste de cada lado.

## Lo que no compensa

Dos técnicas razonables que, medidas sobre este corpus, no mejoraron el
resultado. Se apuntan para no repetir el camino:

**Filtrar por sección antes de buscar.** La idea es buena: si la pregunta es
sobre identificación, no debería ganar un párrafo sobre escrutinio. En la
práctica **baja la utilidad** (de 21 a 17), porque el clasificador de sección
falla justo en las preguntas ambiguas — y cuando falla, **excluye la respuesta
correcta**. Buscar en todo el corpus y dejar que el ranking decida da mejor
resultado.

**Un trozo más grande para «dar contexto».** Anteponer el título de la sección
al texto antes de vectorizar empeoró el acierto (66 % → 75 % al quitarlo). El
prefijo mete ruido en el vector en vez de orientarlo; el contexto útil va en el
campo `tema`, escrito con el vocabulario de quien pregunta.

## Resumen

1. Trocea por unidad de sentido, con un `tema` en palabras de quien pregunta.
   Verifica que cada trozo es literal.
2. Elige el modelo por idioma y por entrenamiento de recuperación. El tamaño,
   después.
3. Calibra el umbral con preguntas etiquetadas, pesando más los falsos
   positivos. Y decide explícitamente entre cobertura y precisión.
