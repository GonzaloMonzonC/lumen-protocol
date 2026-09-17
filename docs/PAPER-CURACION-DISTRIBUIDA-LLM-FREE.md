# Curación distribuida de modelos LLM gratuitos: arquitectura y evaluación empírica de un tejido de inferencia de coste cero para la democratización de la IA

**Gonzalo Monzón**
Proyecto LUMEN (Cadences Lab)
`gonzalo@cadenceslab.com`

---

> **Resumen**
>
> El acceso a modelos de lenguaje de gran escala está mediado por costes de API y por la
> dependencia de un reducido número de proveedores, lo que limita su uso por parte de
> colectivos con presupuesto cero. Las capas gratuitas (*free tiers*) de agregadores como
> OpenRouter ofrecen una alternativa, pero su catálogo es volátil —modelos que aparecen,
> se retiran o degradan sin aviso— y carecen de garantías de servicio, lo que hace inviable
> su uso directo en sistemas autónomos. Presentamos la arquitectura y la evaluación empírica
> de un **tejido de inferencia de coste cero**: un conjunto de nodos heterogéneos (dos
> servidores NAS ARM, un PC, una instancia de máquina virtual propia) que consumen una
> **cadena de modelos gratuitos auto-curada**, mantenida por (i) un agente diario de
> investigación web que descubre candidatos, (ii) un curador que prueba cada candidato con
> una batería ligera de tres sondas (vivacidad, rigor aritmético con restricción de formato,
> estilo con límite de longitud) y publica la cadena ordenada por puntuación, y (iii) las
> propias fuentes, que **re-validan la cadena escalonadas a lo largo del día** y emiten
> opiniones firmadas a un registro central. Sobre una ventana de observación continua de
> ~15,5 horas recogimos **87 validaciones independientes** sobre 14 modelos con latencias
> reales por fuente. Los resultados muestran que (1) es posible sostener un servicio de
> inferencia multi-nodo a **coste $0 ininterrumpidamente y sin intervención humana**;
> (2) la validación multi-fuente revela *flakiness* que una única fuente no ve —la latencia
> del mismo modelo varió 28× (0,9 s–26,2 s) entre fuentes/franjas, y modelos que pasan en
> una ventana fallan en otra—; y (3) el desacuerdo entre fuentes es una señal utilizable
> para retirar modelos inestables. Discutimos las implicaciones para infraestructuras de IA
> soberanas, los límites del estudio, y la extensión del diseño a una red voluntaria tipo
> SETI@home (Lumen@Home) con transporte por radio de bajo ancho de banda (Reticulum/LoRa).
>
> **Palabras clave:** modelos de lenguaje, capas gratuitas, curación automática,
> validación distribuida, computación voluntaria, democratización de la IA, radio mesh.

---

## 1. Introducción

Los grandes modelos de lenguaje (LLM) se han convertido en infraestructura de propósito
general, pero su acceso describe una curva de desigualdad: capacidades de frontera al
alcance de quien puede pagar por token, y millones de usuarios potenciales —escuelas
rurales, bibliotecas comunitarias, ONG, investigadores sin financiación, colectivos
culturales— al margen. La barrera no es solo económica: es también de **dependencia**,
porque operar sobre un único proveedor implica aceptar sus precios, sus políticas y su
disponibilidad.

Una vía intermedia existe: los **catálogos gratuitos** de agregadores como OpenRouter[^1]
publican modelos con precio cero promocional o permanente. Su atractivo es evidente
—potencia de frontera reciente a coste nulo— y sus problemas también: el catálogo rota sin
aviso, los modelos se retiran (`minimax/minimax-m3:free`, retirado el 10-sep-2026, fue
observado en nuestro sistema), el rendimiento fluctúa hora a hora, y **nadie garantiza
nada**: no hay SLA, ni estado publicado, ni histórico.

Este artículo presenta la arquitectura y las mediciones de un sistema que convierte ese
catálogo volátil en un **servicio estable a coste cero** mediante dos ideas sencillas:

1. **Curación automática con guardas**: un agente descubre, un curador prueba y publica,
   y solo entra en producción lo que pasa una batería de sondas — jamás cadenas de menos
   de tres modelos, jamás escrituras sin verificación.
2. **Validación distribuida multi-fuente**: los propios consumidores de la cadena
   (nodos de cómputo heterogéneos) la **re-validan en ventanas horarias distintas** y
   emiten opiniones firmadas a un registro central. La fiabilidad deja de ser una promesa
   del proveedor y pasa a ser una **medición continua de la comunidad de nodos**.

Nuestra contribución es: (a) la arquitectura completa y desplegada, (b) un protocolo de
validación ligero y replicable, (c) un conjunto de observaciones reales en ventana continua
que cuantifica la volatilidad del *free tier* y el valor de medir desde múltiples puntos, y
(d) el diseño de extensión hacia una red voluntaria (Lumen@Home) transportable por radio.

## 2. Trabajo relacionado

**Computación voluntaria.** SETI@home (1999–2020) demostró que millones de voluntarios
donan ciclos ociosos cuando la participación es trivial: 5,2 millones de participantes y
12.000 millones de detecciones[^2]. BOINC[^3] continúa operando ~30 proyectos de ciencia
con el mismo modelo: unidades de trabajo pequeñas, cliente invisible, créditos visibles.
Nuestro diseño de Lumen@Home (§7) traslada ese patrón desde el cómputo numérico hacia la
**validación y el procesamiento de conocimiento** con nodos LLM.

**Enrutado y cascadas de modelos.** La literatura de *frugal AI* propone cascadas
(modelo barato → modelo caro) y enrutadores aprendidos para reducir coste por consulta.
Nuestro sistema comparte el principio de cascada, pero invierte el objeto de optimización:
no buscamos minimizar el coste de un servicio con presupuesto, sino **sostener el servicio
con presupuesto cero**, lo que exige mecanismos de descubrimiento y reparación continuos
que las cascadas estáticas no contemplan.

**Redes tolerantes y mesh por radio.** Reticulum[^4] proporciona un stack de red cifrado
extremo a extremo diseñado para operar sobre medios de muy bajo ancho de banda (LoRa,
packet radio, HF), y Meshtastic[^5] ofrece mallas LoRa de bajo consumo con presets que van
de ~0,2 a ~20 kbps. Ambos son los candidatos naturales para el transporte de coordinación
de una red LUMEN off-grid (§7), dado que las unidades de trabajo de nuestro protocolo son
texto de bytes.

## 3. Arquitectura del sistema

El sistema (desplegado, en producción durante el periodo de estudio) consta de:

| Componente | Descripción | Implementación |
|---|---|---|
| **Nodos** | Ejecutan cargas M y llamadas LLM; 4 fuentes activas en el estudio | NAS ARM (×2, roles distintos), PC de escritorio, instancia MVM local |
| **Cadena** | Lista ordenada de modelos free usada como cascada de fallback | Tabla `^LLMFREE` en la base de datos embebida de cada nodo |
| **Registro central** | API pública de lectura + ingesta de opiniones firmadas | Cloudflare Pages Functions + KV (`cadences.app/api/llmfree`) |
| **Descubridor** | Agente diario que investiga en la web nuevos modelos gratis y deja candidatos | Cron 06:30; escribe candidatos estructurados (JSON) |
| **Curador** | Prueba candidatos + catálogo, puntúa, decide y publica | Cron 07:00; única autoridad que fija la cadena |
| **Fuentes validadoras** | Re-prueban la cadena vigente y opinan | Nodos cada 12 h; PC 15:00; instancia MVM 21:00 |
| **Puerta (gateway)** | Sirve la cadena a las aplicaciones consumidoras leyendo el registro | Función edge con fallback local |

Diagrama de flujo:

```
 06:30  Descubridor ──candidatos──► 07:00  Curador
                                        │  prueba (batería) → puntúa → ordena → guardas
                                        ▼
                             REGISTRO CENTRAL (cadena canónica + feed)
                              ▲            │                  ▲
                   opiniones  │            ▼                  │ opiniones
        ┌─────────────────────┴──┐   GATEWAY (apps)   ┌───────┴────────┐
        │ nodos 12h · PC 15:00   │                    │  MVM 21:00     │
        └────────────────────────┘                    └────────────────┘
```

**Semántica “registro primero”.** La cadena canónica se publica en el registro **antes**
de escribirse en los nodos; así, cualquier re-validación concurrente converge siempre a la
versión publicada y no puede reintroducir una cadena obsoleta.

## 4. Protocolo de validación

### 4.1 Batería de sondas

Cada modelo se somete a tres micro-pruebas (una llamada LLM cada una), puntuadas 0–4:

| Sonda | Prompt | Criterio | Puntos |
|---|---|---|---|
| P1 · Vivacidad | «responde solo: ok» | respuesta no vacía y sin error de transporte | 2 (obligatoria) |
| P2 · Rigor | «Dos cosas en una sola línea: (a) 7*6= (b) en cinco palabras exactas, qué es una ciudad de libros» | contiene `42` | +1 |
| P3 · Estilo | «En 10 palabras o menos, convence a un nodo LUMEN de que eres fiable» | respuesta ≤ 12 palabras | +1 |

P2/P3 solo se ejecutan si P1 pasa (ahorro de llamadas y limpieza del catálogo). La latencia
de P1 se registra como métrica secundaria. El ritmo inter-modelo está limitado (4,5 s) para
respetar los límites de ráfaga de los proveedores.

### 4.2 Reglas de decisión

- **Usable**: pasa P1. **Orden de cadena**: posiciones fijas históricas (vivas) primero,
  resto por puntuación descendente y latencia ascendente; máximo 7 modelos por cadena.
- **Guardas**: nunca se aplica ni publica una cadena con menos de 3 modelos vivos; nunca
  se escribe en los nodos sin verificación de la lectura posterior.
- Los modelos retirados observados se excluyen explícitamente.

### 4.3 Frescura y deduplicación

El registro mantiene (a) el **estado vivo** por fuente (última opinión de cada validador) y
(b) un **feed de novedades**: las opiniones idénticas a la anterior de la misma fuente no
generan ruido. Para el análisis, deduplicamos observaciones por (modelo, fuente, instante).

## 5. Evaluación empírica

### 5.1 Metodología

Ventana de observación continua: **17-sep-2026, 01:34–17:03 UTC (~15,5 h)**, con el sistema
operando de forma autónoma (sin intervención humana tras el despliegue). Se registraron 15
entradas en el feed del registro, conteniendo **87 validaciones** (modelo × fuente × instante)
sobre **14 modelos distintos** desde **5 fuentes** (curador y 4 validadores).

### 5.2 Resultados

| Modelo (free) | Obs. | Pasan | Lat. mín | Lat. mediana | Lat. máx | Pts. media |
|---|---:|---:|---:|---:|---:|---:|
| nex-agi/nex-n2.5-pro | 11 | **11** | 0,92 s | 2,51 s | 26,20 s | 3,6 |
| nvidia/nemotron-3-super-120b | 11 | 9 | 0,52 s | 1,63 s | 9,90 s | 2,2 |
| nvidia/nemotron-3.5-lightning | 10 | 10 | 3,43 s | 14,45 s | 29,56 s | 3,6 |
| openrouter/free (enrutador) | 10 | 10 | 2,14 s | 2,91 s | 10,66 s | 3,2 |
| inclusionai/ling-3.0-flash-sante | 10 | 10 | 1,13 s | 2,49 s | 10,08 s | 3,0 |
| nvidia/nemotron-3-ultra-550b | 9 | 7 | 1,17 s | 9,97 s | 13,60 s | 3,8 |
| nex-agi/nex-n2.5-mini | 8 | 7 | 1,83 s | 5,95 s | 9,87 s | 3,8 |
| *(5 modelos con ≤ 4 obs.)* | 18 | 11 | — | — | — | — |

**Hallazgos principales:**

1. **Viabilidad a coste cero y sin humano.** Durante 15,5 h, el servicio se mantuvo con
   cadenas de 7 modelos, incluyendo la **entrada autónoma de 4 modelos nuevos** al catálogo
   (descubrimiento web → prueba → cadena) y la retirada implícita de modelos flojos, sin
   ninguna intervención humana. Coste total de inferencia: $0.
2. **La varianza inter-fuente es enorme y medible.** El mismo modelo registró latencias de
   0,92 s (PC, 15:00) a 26,20 s (curador, 07:00) — una dispersión de **28×** — y
   `nemotron-3.5-lightning` osciló entre 3,4 s y 29,6 s según la franja. Una fuente única
   habría reportado una foto estática; cinco fuentes escalonadas revelan el perfil real.
3. **El desacuerdo entre fuentes identifica modelos inestables.** En una auditoría manual
   de 28 llamadas, `lightning` y el enrutador `openrouter/free` fallaron con timeouts;
   en las ventanas medidas por los nodos pasaron. La conclusión operativa no es “el modelo
   falla” sino “**este modelo es intermitente**” — y el sistema lo retira o lo degrada con
   esa evidencia acumulada, no con una impresión puntual.
4. **Los micro-probes separan modelos que la vivacidad confunde.** `nemotron-3-super`
   aprueba vivacidad pero puntúa 2,2/4 (responde en inglés a prompts en castellano,
   formato irregular), mientras `nex` y `ultra` puntúan 3,8/4. La puntuación permite
   *ordenar* la cascada, no solo filtrar.

### 5.3 Límites del estudio

Ventana corta (15,5 h) y N pequeño; un solo agregador de origen (OpenRouter); sondas
deliberadamente ligeras (miden vivacidad, aritmética trivial, restricción de formato —
**no** calidad de razonamiento largo ni fidelidad factual); latencias auto-reportadas por
los validadores (incluyen su propio overhead, lo que es a la vez métrica de servicio
percibido); y volatilidad intrínseca del objeto de estudio (los resultados de mañana no
serán los de hoy — precisamente el punto). Los datos completos quedan versionados en el
repositorio del proyecto para su re-análisis.

## 6. Discusión

Tres consecuencias nos parecen generalizables:

- **La fiabilidad como medición, no como promesa.** Donde no hay SLA, el sustituto es
  evidencia distribuida continua: varias fuentes, franjas escalonadas y un registro público.
  El coste marginal de esa evidencia es ~0 porque reutiliza los propios nodos consumidores.
- **La volatilidad del free tier es gestionable con guardas conservadoras.** La clave no es
  elegir bien una vez, sino *nunca quedarse sin cadena*: umbral de 3 modelos, cascada con
  fallback, publicación atómica y curación diaria. El sistema tolera que un modelo muera en
  cualquier momento porque su muerte es detectable en horas, no en incidencias.
- **La democratización requiere infraestructura mínima, no máxima.** El binario completo de
  un nodo ocupa ~4 MB y corre en hardware de desecho; el coste de reproducción del diseño es
  prácticamente nulo. Esto invierte la intuición dominante (más GPUs) y sugiere que la
  palanca real es de **red y protocolo**, no de cómputo.

## 7. Trabajo futuro: Lumen@Home y radio

**Lumen@Home (computación voluntaria).** Las validaciones descritas son, en esencia,
**unidades de trabajo** con todas las primitivas ya construidas: petición, ejecución con
límite de recursos, firma del resultado y agregación en un registro. La extensión natural es
abrir el circuito a voluntarios (`mvm-nas --volunteer <url>`): validación por quórum 2-de-3,
reputación simple y permisos delegables mediante *macaroons*, siguiendo las lecciones de
BOINC/SETI@home[^2][^3]: unidad pequeña, cliente invisible, crédito visible.

**Transporte por radio.** Las unidades de trabajo del sistema son texto de bytes y JSON de
kilobytes: **la capa de coordinación completa cabe en un canal de ~1 kbps**. Sobre Reticulum[^4]
(cifrado extremo a extremo sobre LoRa/packet/HF) o mallas Meshtastic[^5], un nodo equipado
con un módulo LoRa (~€20–40) puede recibir trabajo, ejecutarlo contra un modelo **local**
(llama.cpp/Ollama, sin Internet) y devolver el resultado firmado. Esa combinación —modelo
local + radio— cierra el círculo de la soberanía: el nodo deja de necesitar la nube, no por
ideología, sino por física del medio.

## 8. Reproducibilidad

- **Registro público** (lectura): `https://cadences.app/api/llmfree` y `/hist` — cadena
  canónica, opiniones por fuente y feed de novedades con puntuaciones y latencias.
- **Datos del estudio**: volcados en el repositorio del proyecto (`cadenceslab-social`,
  carpeta `modelos-free/`: informes diarios, `historial.jsonl`, digests de investigación).
- **Componentes**: nodos (binario ARM ~4 MB + base embebida), curador y validadores
  (scripts), batería de sondas descrita en §4.1. Partes del sistema son privadas por
  contener despliegues personales; el protocolo completo se describe aquí para su
  reimplementación independiente.

## 9. Conclusión

Un catálogo de modelos gratuitos, tratado como **recurso comunitario medido**, puede sostener
servicios de inferencia reales a coste cero y sin operador humano: descubrimiento diario,
curación con guardas, publicación canónica y validación distribuida escalonada. La medición
multi-fuente no es un lujo metodológico: es el mecanismo que convierte la volatilidad de los
*free tiers* en información accionable. Los siguientes pasos —unidades de trabajo abiertas a
voluntarios y transporte por radio de bajo ancho de banda— extienden el mismo diseño hasta
una red que puede operar sin datacenter, sin tarjeta y, si hace falta, sin Internet.

> «SETI@home buscaba señales de otros. Lumen@Home reparte la inteligencia entre nosotros.»
> Y por radio, si hace falta. 📡

---

## Referencias

[^1]: OpenRouter — API unificada de modelos (endpoint público `/api/v1/models` con precios).
[^2]: SETI@home (Berkeley SETI Research Center, 1999–2020; >5,2 M participantes; 12·10⁹ detecciones). Documentación histórica y nota de hibernación de marzo de 2020.
[^3]: BOINC — Berkeley Open Infrastructure for Network Computing (Universidad de California, Berkeley); ~30 proyectos activos de computación voluntaria.
[^4]: Reticulum Network Stack — *«the cryptography-based networking stack for building unstoppable networks with LoRa, Packet Radio, WiFi and everything in between»*; `rnx`/`rncp` operan sobre enlaces de muy bajo ancho de banda.
[^5]: Meshtastic — mallas LoRa de bajo consumo; presets de módem de ~0,2 kbps (LongSlow) a ~20 kbps (ShortTurbo), con restricciones de ciclo de trabajo según banda ISM.
[^6]: Sistema propio: nodos MVM (mvm-nas), rutinas M de curación y validación, registro central en Cloudflare (Pages Functions + KV) y puerta de inferencia con lectura dinámica de la cadena.

*Manuscrito preparado el 17 de septiembre de 2026. Datos: ventana 01:34–17:03 UTC del 17-sep-2026, 87 validaciones, 14 modelos, 5 fuentes. Repositorio: lumen-protocol (docs/).*
