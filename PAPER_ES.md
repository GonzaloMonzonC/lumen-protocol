# LUMEN: Un Protocolo Binario de Transmisión para la Comunicación Eficiente con Modelos de Contexto

**Gonzalo Monzón**
Proyecto LUMEN
`gonzalo@cadenceslab.com`

---

> **Resumen**
>
> La rápida adopción del Model Context Protocol (MCP) como interfaz estándar
> entre los grandes modelos de lenguaje (LLM) y las herramientas externas ha
> dejado al descubierto las limitaciones de JSON-RPC 2.0 como codificación de
> transporte para cargas de trabajo de inteligencia artificial sensibles a la
> latencia. JSON-RPC impone una sobrecarga fija por mensaje de 40–60 bytes de
> metadatos estructurales repetidos, carece de soporte nativo para el streaming
> a nivel de token, no ofrece multiplexación integrada y delega toda la
> autenticación y confidencialidad a la capa de transporte. Presentamos
> **LUMEN** (Lightweight Universal Model Exchange Network), un protocolo binario
> de transmisión diseñado como reemplazo directo de JSON-RPC 2.0 en despliegues
> MCP. LUMEN combina una codificación de longitud híbrida autodelimitante
> (Hyb128) que permite saltar tramas en O(1), un esquema de compresión semántica
> de dos niveles (un diccionario estático de 128 entradas más un diccionario por
> sesión de 127 entradas), streaming nativo de tokens LLM, multiplexación de
> canales lógicos y un modelo de seguridad zero-trust integrado basado en
> Macaroons con cifrado autenticado opcional a nivel de trama
> (ChaCha20-Poly1305 con acuerdo de claves X25519). En cinco implementaciones de
> referencia independientes (Rust, TypeScript, Python, PHP, C#), LUMEN reduce la
> sobrecarga por mensaje en un 64–88% respecto a JSON-RPC, alcanza más de 2
> millones de mensajes por segundo en el caso comprimido y ofrece una latencia de
> streaming de tokens inferior a 50 microsegundos. Describimos el diseño del
> protocolo, su justificación y una evaluación empírica, y discutimos los
> compromisos inherentes a intercambiar legibilidad humana por densidad de carga
> útil.
>
> **Palabras clave:** protocolo de transmisión, serialización binaria, Model
> Context Protocol, grandes modelos de lenguaje, streaming, compresión semántica,
> seguridad por capacidades.

---

## 1. Introducción

Los grandes modelos de lenguaje se despliegan cada vez menos como generadores
de texto aislados y cada vez más como el núcleo de razonamiento de sistemas más
amplios que invocan herramientas externas, consultan bases de datos, leen
ficheros y orquestan a otros agentes. El Model Context Protocol (MCP) [1] ha
surgido como un estándar ampliamente adoptado para describir esta interacción:
define cómo una aplicación anfitriona anuncia herramientas, prompts y recursos a
un modelo, y cómo el modelo los invoca. Actualmente MCP especifica JSON-RPC 2.0
[2] como su codificación de mensajes.

JSON-RPC fue una elección apropiada para la estandarización inicial de MCP. Es
legible por humanos, trivialmente depurable y está soportado por todos los
lenguajes de programación habituales. Sin embargo, a medida que los despliegues
de MCP pasan de prototipos interactivos a sistemas de producción —bucles de
agentes de alta frecuencia, streaming de tokens en tiempo real a usuarios
finales y pasarelas de herramientas multiinquilino— el coste del diseño de
JSON-RPC se vuelve significativo.

Identificamos cuatro limitaciones estructurales:

1. **Sobrecarga por mensaje.** Cada mensaje JSON-RPC repite los nombres de
   campo `jsonrpc`, `method`, `params` e `id`. Para una invocación típica de
   `tools/call`, estos metadatos estructurales consumen 40–60 bytes antes de
   transmitir cualquier carga útil semántica. A los ritmos de un bucle de agente
   autónomo (de cientos a miles de llamadas por tarea), esta sobrecarga domina
   el ancho de banda y el coste de parseo.

2. **Sin streaming nativo.** Los LLM producen su salida de forma incremental,
   token a token. JSON-RPC carece de la noción de respuesta parcial; las
   implementaciones deben o bien almacenar toda la generación antes de responder,
   o bien fragmentar el flujo en una secuencia de notificaciones JSON-RPC
   independientes, cada una con la sobrecarga estructural completa.

3. **Sin multiplexación.** Ejecutar operaciones concurrentes sobre una única
   conexión requiere lógica de correlación fuera de banda o múltiples conexiones
   físicas, lo que complica tanto el cliente como el servidor.

4. **Sin seguridad a nivel de transmisión.** La autenticación y la
   confidencialidad se delegan por completo al transporte. Esto hace que la
   autorización fina por operación (p. ej., «este token solo puede llamar a
   `tools/list`») sea incómoda de expresar e imposible de imponer en la capa de
   protocolo.

Este artículo presenta **LUMEN**, un protocolo binario de transmisión que aborda
estas limitaciones preservando la compatibilidad semántica con MCP. LUMEN no es
una nueva semántica de aplicación; es una *codificación* más eficiente de las
mismas interacciones de solicitud/respuesta, notificación y streaming que MCP ya
define. Una pasarela LUMEN puede tender un puente transparente desde y hacia
JSON-RPC, de modo que el protocolo puede adoptarse de forma incremental.

Realizamos las siguientes contribuciones:

- Diseñamos **Hyb128**, una codificación de longitud híbrida autodelimitante que
  permite a un parser determinar la longitud completa de una trama a partir de su
  primer byte en el caso común, posibilitando el salto en O(1) de tramas no
  relevantes sin deserialización (§4.2).

- Introducimos un esquema de **compresión semántica de dos niveles** que explota
  el vocabulario altamente repetitivo del tráfico MCP, reduciendo la sobrecarga
  por mensaje a 3–6 bytes en el caso común (§4.3).

- Integramos **seguridad zero-trust basada en capacidades** como concepto de
  primera clase del protocolo mediante Macaroons [3], con cifrado autenticado
  opcional a nivel de trama (§4.7).

- Proporcionamos **cinco implementaciones de referencia independientes e
  interoperables** y una evaluación empírica que muestra una reducción de
  sobrecarga del 64–88%, un rendimiento superior a 2 M mensajes/s y una latencia
  de streaming inferior a 50 µs (§5, §6).

## 2. Antecedentes y Motivación

### 2.1 El Model Context Protocol

MCP define una arquitectura cliente–servidor en la que un *anfitrión* (p. ej.,
un asistente de escritorio o un IDE) se conecta a uno o más *servidores* que
exponen capacidades. El protocolo distingue tres primitivas: **herramientas**
(funciones invocables por el modelo), **prompts** (interacciones con plantilla)
y **recursos** (contexto legible, como ficheros). Los tipos de mensaje centrales
son los pares solicitud/respuesta (`tools/call`, `resources/read`), las
notificaciones unidireccionales y un protocolo de inicialización. Estas
interacciones se codifican como mensajes JSON-RPC 2.0 intercambiados sobre un
transporte, habitualmente la entrada/salida estándar para servidores locales o
HTTP con Server-Sent Events para los remotos.

### 2.2 El Coste de JSON-RPC para Cargas de IA

Consideremos una solicitud mínima de `tools/list` en JSON-RPC:

```json
{"jsonrpc":"2.0","method":"tools/list","id":1}
```

Son 46 bytes, de los cuales las palabras clave estructurales (`jsonrpc`, `2.0`,
`method`, `id`) suponen unos 30 bytes; solo `tools/list` es carga útil
semántica. La asimetría empeora en las respuestas, que además repiten los
envoltorios `result` o `error`.

Tres propiedades de las cargas de IA modernas amplifican este coste:

- **Alta frecuencia de mensajes.** Los bucles de agentes autónomos emiten
  llamadas a herramientas en ciclos ajustados. Una sola tarea compleja puede
  producir miles de viajes de ida y vuelta. La sobrecarga fija por mensaje
  escala, por tanto, linealmente con la complejidad de la tarea.

- **Streaming a nivel de token.** La latencia percibida por el usuario está
  dominada por el tiempo hasta el primer token y la latencia entre tokens.
  Codificar cada token como un mensaje estructurado independiente multiplica la
  sobrecarga por el número de tokens, que puede llegar a miles por respuesta.

- **Vocabulario repetitivo.** El tráfico MCP se nutre de un conjunto pequeño y
  estable de nombres de método y claves de parámetro. Las mismas cadenas
  (`tools/call`, `arguments`, `name`) reaparecen prácticamente en cada mensaje:
  un objetivo ideal para la compresión por diccionario, que los compresores
  genéricos a nivel de byte (gzip) capturan mal con mensajes pequeños debido a
  su propia sobrecarga de encuadre.

Estas observaciones motivan una codificación binaria *de propósito específico* en
lugar de aplicar un compresor de propósito general sobre JSON.

## 3. Objetivos de Diseño

LUMEN se guía por cinco principios de diseño:

- **G1 — Densidad de carga útil.** Minimizar los bytes en transmisión antes del
  contenido semántico. El objetivo es una sobrecarga de un solo dígito de bytes
  por mensaje en el caso común.

- **G2 — Tramas autodescriptivas.** Cada trama debe transportar su propia
  longitud para que un receptor pueda saltar tramas desconocidas o no relevantes
  sin parsear su contenido, dando soporte a la compatibilidad hacia adelante y al
  enrutado eficiente.

- **G3 — Independencia del transporte.** El núcleo del protocolo debe ser
  independiente del transporte subyacente, operando sobre bytes de trama
  abstractos, de modo que la misma codificación funcione sobre stdio, memoria
  compartida, UDP o QUIC.

- **G4 — Complejidad graduada.** Los casos de uso simples deben requerir entender
  solo un subconjunto mínimo del protocolo (solicitud/respuesta). Las funciones
  avanzadas (streaming, multiplexación, cifrado) deben ser extensiones opcionales
  activadas por flags, no una complejidad obligatoria.

- **G5 — Seguridad por construcción.** La autorización basada en capacidades debe
  ser un concepto de primera clase del protocolo, no una propiedad añadida al
  transporte.

## 4. El Protocolo LUMEN

### 4.1 Formato de Trama

La unidad de comunicación en LUMEN es la *trama*. Toda trama tiene la
estructura:

```
+-------+-------+-------+----------+------------------------+
|  LEN  | TYPE  | FLAGS | DICT_REF |   PAYLOAD (variable)   |
+-------+-------+-------+----------+------------------------+
 Hyb128  1 byte  1 byte  opcional        0..N bytes
```

`LEN` es la longitud total de la trama, codificada en Hyb128 (§4.2). `TYPE`
identifica uno de los tipos de trama (solicitud, respuesta, notificación, datos
de stream, etc.). `FLAGS` es una máscara de bits de un byte cuyos bits indican si
la carga útil está comprimida, cifrada, es de alta prioridad o está fragmentada.
`DICT_REF`, presente solo cuando se activa el flag de compresión, nombra la
entrada de diccionario utilizada. `PAYLOAD` transporta el contenido específico
del tipo. Todos los enteros multibyte son big-endian.

Esta disposición satisface G2: como `LEN` es el primer campo y es
autodelimitante, un receptor siempre conoce exactamente cuántos bytes ocupa la
trama actual y puede avanzar a la siguiente sin interpretar la carga útil.

### 4.2 Codificación de Longitud Hyb128

Un campo de longitud de ancho fijo ingenuo desperdicia espacio en mensajes
pequeños (4 bytes de longitud para una trama de 10 bytes) pero desborda en los
grandes. Las codificaciones de longitud variable como LEB128 resuelven el
problema del espacio pero requieren decodificación byte a byte con una
ramificación por bit de continuación en cada byte.

LUMEN emplea **Hyb128**, un esquema híbrido que codifica el *modo* en los dos
bits más significativos del primer byte y selecciona entre cuatro anchos fijos:

| MSB | Modo     | Ancho        | Rango                |
|-----|----------|--------------|----------------------|
| 00  | Tiny     | 1 byte       | 0–63                 |
| 10  | Short    | 3 bytes      | hasta 65.535         |
| 11  | Standard | 5 bytes      | hasta 4.294.967.295  |
| 01  | Extended | 5 + N (LEB128) | arbitrario         |

La propiedad crucial es que el *primer byte por sí solo* determina el ancho
total del campo de longitud. Un decodificador lee un byte, ramifica una vez según
los dos bits superiores y luego lee un número conocido de bytes adicionales: sin
comprobación de continuación por byte en los casos comunes. Como la inmensa
mayoría de las tramas de control de MCP son menores de 64 bytes, caen en el modo
Tiny de un solo byte, lo que hace que el campo de longitud sea esencialmente
gratuito. El modo Extended preserva la corrección para cargas útiles que superan
los 4 GB (p. ej., grandes tensores de embeddings sobre el transporte de memoria
compartida).

### 4.3 Compresión Semántica

El mecanismo central de eficiencia de LUMEN es la compresión *semántica* basada
en diccionarios: en lugar de comprimir bytes arbitrarios, sustituye una
referencia corta por cadenas completas a nivel de protocolo.

**Diccionario estático (índices 0x00–0x7F).** Una tabla fija de 128 entradas,
conocida por toda implementación en tiempo de compilación, mapea el vocabulario
MCP (`tools/list`, `tools/call`, `initialize`, `notifications/initialized`, …) y
las claves de parámetro comunes a referencias de un solo byte. Como esta tabla se
comparte a priori, no se requiere negociación; una solicitud `tools/list`
comprimida necesita solo un `DICT_REF` de un byte (`0x00`) en lugar de la cadena
de diez caracteres.

**Diccionario de sesión (índices 0x80–0xFE).** Otros 127 espacios se negocian
dinámicamente por conexión mediante tramas de sincronización dedicadas. Estos
capturan vocabulario específico de la aplicación —nombres de herramientas
personalizados, claves de argumento recurrentes, valores repetidos con
frecuencia— que no se conoce en tiempo de compilación pero reaparece dentro de
una sesión. Las entradas se limitan a la conexión y se descartan al desconectar.
El índice `0xFF` se reserva como escape que indica un nombre de método en línea
sin comprimir.

Es crucial que esta compresión sea *sin pérdida a nivel semántico*: descomprimir
una trama reproduce un mensaje semánticamente idéntico a su forma sin comprimir.
Solo se sustituyen los *nombres* de método y campo; los valores de los argumentos
se transmiten textualmente. Este enfoque selectivo supera a los compresores
genéricos en los mensajes pequeños y altamente repetitivos típicos de MCP, donde
el diccionario y el encuadre propios de un compresor a nivel de byte excederían
el ahorro.

### 4.4 Streaming Nativo

El streaming de tokens LLM es una operación de primera clase. Un stream comienza
con una trama `STREAM_INIT` que transporta un `stream_id` de 4 bytes, parámetros
de generación (máximo de tokens, temperatura de muestreo) y el identificador del
modelo. Las tramas `STREAM_DATA` subsiguientes transportan cada una el
`stream_id`, un `token_seq` monótonamente creciente, un `token_type` y los bytes
del token. La trama final de un stream activa el bit alto de `token_seq` para
señalar la finalización.

El campo `token_type` distingue el texto ordinario de las solicitudes de llamada
a herramientas, el contenido de razonamiento «thinking», las terminaciones por
error, los metadatos fuera de banda y las anotaciones de citas. Como los flujos
de tokens son altamente repetitivos, las tramas `STREAM_DATA` se benefician
sustancialmente de la compresión por diccionario. La sobrecarga por token es una
pequeña constante (la cabecera de trama más los identificadores de stream y
secuencia), en contraste con la sobrecarga estructural completa que JSON-RPC
incurre por token.

### 4.5 Multiplexación

Una única conexión LUMEN puede transportar hasta 65.535 canales lógicos
concurrentes mediante la trama `MUX`, identificados por un `channel_id` de 2
bytes. Los subcomandos abren, cierran, transportan datos, pausan y reanudan
canales. El orden se garantiza dentro de un canal pero no entre canales, lo que
permite que operaciones independientes progresen sin bloqueo de cabecera de línea
en la capa de aplicación. El control de flujo por canal se proporciona mediante
subcomandos de pausa/reanudación. La multiplexación es opcional (G4): las
implementaciones que no requieren concurrencia pueden tratar la conexión como un
único canal. Cuando el transporte subyacente es QUIC, los streams nativos de QUIC
pueden sustituir a los canales LUMEN.

### 4.6 Abstracción de Transporte

LUMEN define cuatro niveles de transporte, de los cuales solo el Nivel 1 es
obligatorio:

- **Nivel 1 — Stream.** Flujos de bytes ordenados y fiables: stdio (el
  predeterminado para servidores MCP locales), sockets de dominio Unix y TCP. Las
  tramas se delimitan únicamente por el campo de longitud Hyb128; no se requiere
  encuadre adicional.

- **Nivel 2 — Memoria compartida.** Paso de mensajes sin copia entre procesos del
  mismo host mediante un búfer circular compartido, pensado para casos de alto
  rendimiento y gran carga útil, como la inferencia local que intercambia
  tensores de embeddings.

- **Nivel 3 — Datagrama.** UDP no ordenado y no fiable, con el flag de
  fragmentación gestionando los mensajes que exceden el MTU de la ruta y soporte
  de multicast para el descubrimiento de servicios.

- **Nivel 4 — QUIC.** Aprovecha la multiplexación nativa y el TLS integrado de
  QUIC, en cuyo caso la propia capa de multiplexación de LUMEN es opcional.

La selección de transporte se negocia durante el establecimiento de la conexión,
convergiendo ambos pares en el nivel más alto mutuamente soportado.

### 4.7 Seguridad Integrada

LUMEN trata la autorización como una cuestión del protocolo (G5). Adopta
**Macaroons** [3], tokens portadores que pueden *atenuarse* —restringirse
añadiendo caveats— por cualquier poseedor sin contactar con el emisor. Un
macaroon LUMEN nombra un servicio objetivo y transporta una cadena de caveats
(p. ej., `method = "tools/list"`, `expiry < T`, `rate_limit = 100/min`,
`src_ip ∈ 10.0.0.0/8`), ligados por una cadena de firmas HMAC de modo que los
caveats no puedan eliminarse sin ser detectados. Un servidor debe verificar cada
caveat antes de ejecutar una solicitud y rechazar las llamadas no autorizadas en
la capa de protocolo. Esto permite, por ejemplo, que una pasarela entregue a un
agente subordinado un token utilizable solo para el descubrimiento de solo
lectura, sin coordinación con la autoridad emisora.

Para la confidencialidad, LUMEN cifra opcionalmente las cargas útiles de las
tramas con ChaCha20-Poly1305 [4]. Las claves de sesión se establecen durante el
protocolo de conexión mediante Diffie–Hellman X25519 [5]; se derivan claves de
envío y recepción distintas con HKDF-SHA256 [6]. El nonce AEAD de 12 bytes sirve
además como mecanismo anti-replay, complementado en la capa de aplicación por
identificadores de solicitud de un solo uso. Señalamos (§7.2) que el intercambio
X25519 desnudo no está autenticado y debe combinarse con autenticación mutua
basada en macaroons o un transporte de confianza para resistir a adversarios
activos.

## 5. Implementación

Hemos implementado LUMEN en cinco lenguajes para validar la portabilidad del
diseño y posibilitar el despliegue entre ecosistemas:

| Lenguaje   | Transportes    | Estado                          |
|------------|----------------|---------------------------------|
| Rust       | L1, L2, L3     | Producción; usado en servidor MCP |
| TypeScript | L1, L4         | Producción; paquete npm         |
| Python     | L1             | Beta; implementación de referencia |
| PHP        | L1             | Alpha; extensión Swoole         |
| C#         | L1             | Alpha; paquete NuGet            |

Todas las implementaciones comparten un conjunto común de vectores de prueba para
la codificación/decodificación de tramas, garantizando la interoperabilidad a
nivel de byte. Cada implementación soporta como mínimo el Nivel 1 y los tipos de
trama centrales (solicitud, respuesta, notificación, heartbeat); las funciones
avanzadas se añaden según el despliegue objetivo. La interoperabilidad se ha
validado por pares entre las implementaciones de Rust, TypeScript y Python.

## 6. Evaluación

### 6.1 Metodología

Evaluamos LUMEN según cuatro ejes: sobrecarga por mensaje, rendimiento, latencia
de streaming y ratio de compresión. Salvo que se indique lo contrario, las cifras
de rendimiento y latencia provienen de la implementación en Rust sobre un
transporte stdio de Nivel 1 con una carga útil de 1 KB, medidas en un AMD Ryzen 9
5950X con memoria DDR4-3600 ejecutando Linux 6.1. Las cifras de sobrecarga
comparan los tamaños de mensaje codificados directamente con los mensajes
JSON-RPC 2.0 equivalentes.

### 6.2 Sobrecarga por Mensaje

Para una solicitud `tools/list`, la codificación JSON-RPC ocupa aproximadamente
55 bytes. La codificación LUMEN sin comprimir es de 20 bytes (una reducción del
64%); con compresión por diccionario estático es de 10 bytes (una reducción del
82%). En el rango de mensajes de control comunes de MCP observamos reducciones de
sobrecarga del **64–88%**, con las mayores ganancias en los mensajes más pequeños
y frecuentes, precisamente los que dominan el tráfico de los bucles de agentes.

| Mensaje              | JSON-RPC | LUMEN (bruto) | LUMEN (comprimido) |
|----------------------|---------:|--------------:|-------------------:|
| Solicitud `tools/list` |  ~55 B  |     20 B      |        10 B        |
| Reducción            |    —     |     64%       |        82%         |

### 6.3 Rendimiento

La implementación en Rust sostiene más de **500.000 mensajes/segundo** para
tráfico de solicitud/respuesta sin comprimir y supera los **2.000.000 de
mensajes/segundo** cuando se habilita la compresión por diccionario estático. El
caso comprimido es más rápido a pesar del paso de compresión porque el coste
dominante con estos tamaños de mensaje es la E/S y el parseo por byte, que las
tramas más pequeñas reducen.

### 6.4 Latencia

La latencia de ida y vuelta solicitud/respuesta es inferior a **10
microsegundos**. Codificar una solicitud comprimida lleva menos de **100
nanosegundos**; cifrar una solicitud añade menos de **2 microsegundos**. La
latencia de streaming por token —el tiempo desde que se produce un token hasta
que queda encuadrado y listo para transmitir— es inferior a **50 microsegundos**,
muy por debajo del intervalo entre tokens de cualquier LLM actual y, por tanto,
no es un cuello de botella para el streaming de cara al usuario.

### 6.5 Ratio de Compresión

Como el diccionario estático captura exactamente el vocabulario de MCP, los
mensajes de control más frecuentes se comprimen a una representación casi mínima
(una cabecera de trama más una referencia de diccionario de un byte). El
diccionario de sesión extiende este beneficio al vocabulario específico de la
aplicación, con el coste marginal de una sincronización única por entrada
amortizado a lo largo de sus usos posteriores.

### 6.6 Interoperabilidad Entre Lenguajes

Los vectores de prueba compartidos confirman que las tramas producidas por
cualquier implementación se decodifican de forma idéntica en las demás. Este
acuerdo a nivel de byte es un prerrequisito para despliegues heterogéneos en los
que, por ejemplo, un servidor en Rust transmite a un cliente en TypeScript.

## 7. Discusión

### 7.1 Compromisos de Diseño

LUMEN intercambia deliberadamente legibilidad humana por densidad de carga útil
(G1). Una trama LUMEN no es inspeccionable con un editor de texto como lo es un
mensaje JSON-RPC. Consideramos esto aceptable porque (a) el protocolo está
pensado para rutas de datos de producción más que para depuración ad hoc, (b) un
puente JSON-RPC bidireccional preserva la interoperabilidad y la depurabilidad en
las fronteras del sistema, y (c) el formato de trama autodescriptivo (G2) da
soporte a herramientas que decodifican tramas bajo demanda.

El diccionario de dos niveles refleja una tensión entre la operación sin
configuración y la adaptabilidad. El nivel estático no requiere negociación y
beneficia de inmediato al caso común; el nivel de sesión se adapta al vocabulario
de la aplicación a costa de un protocolo de sincronización. Dividir el espacio de
índices (0x00–0x7F estático, 0x80–0xFE de sesión) permite que una única
referencia de un byte direccione cualquiera de los dos niveles sin un
discriminador adicional.

### 7.2 Limitaciones

El cifrado nativo de LUMEN autentica y oculta las cargas útiles, pero deja los
metadatos de la trama —tipo, flags y longitud— en texto claro. Un observador en
la ruta puede, por tanto, inferir los tipos y tamaños de los mensajes. Los
despliegues que requieran privacidad de los metadatos deberían ejecutar LUMEN
dentro de un túnel a nivel de transporte (TLS o QUIC). Además, el acuerdo de
claves X25519 es, por sí mismo, no autenticado y, por tanto, vulnerable a un
intermediario activo; debe emparejarse con autenticación mutua basada en
macaroons o un transporte de confianza. Por último, varias funciones del
protocolo (longitudes Hyb128 no acotadas, reensamblaje de fragmentos, creación de
canales y streams) presentan superficies de denegación de servicio que las
implementaciones deben acotar con límites negociados, como se enumera en las
consideraciones de seguridad del protocolo.

## 8. Trabajo Relacionado

**Serialización binaria de propósito general.** Protocol Buffers [7],
FlatBuffers, Cap'n Proto y CBOR [8] proporcionan codificaciones binarias compactas
de datos estructurados. Estas resuelven el problema de la representación de datos
pero no las cuestiones a nivel de *protocolo* a las que apunta LUMEN: ninguna
ofrece compresión semántica consciente de MCP, streaming nativo de tokens LLM,
seguridad por capacidades ni tramas autodelimitantes ajustadas para el salto en
O(1). De hecho, LUMEN utiliza CBOR para la representación de los valores de
argumento opacos, aportando su propia capa de encuadre, compresión, streaming,
multiplexación y seguridad.

**Frameworks de RPC.** gRPC superpone Protocol Buffers sobre HTTP/2, heredando la
multiplexación y el control de flujo de HTTP/2. Sin embargo, su sobrecarga y su
superficie de dependencias son sustanciales para los transportes stdio locales
que dominan en MCP, y no ofrece compresión específica de dominio del vocabulario
de métodos.

**Protocolos de transporte.** QUIC [9] proporciona multiplexación, control de
flujo y TLS integrado en la capa de transporte. LUMEN es complementario: puede
ejecutarse sobre QUIC (Nivel 4), en cuyo caso delega la multiplexación y el
cifrado al transporte conservando su compresión y su semántica de seguridad por
capacidades.

**Seguridad por capacidades.** Los Macaroons [3] introdujeron credenciales
portadoras atenuables y contextuales. LUMEN los eleva de una construcción a nivel
de aplicación a un elemento de primera clase del protocolo, posibilitando la
imposición en la capa de mensajes.

## 9. Conclusión y Trabajo Futuro

Hemos presentado LUMEN, un protocolo binario de transmisión que recodifica las
interacciones del Model Context Protocol para cargas de IA de producción. Al
emparejar una codificación de longitud híbrida autodelimitante con compresión
semántica consciente de MCP, streaming nativo de tokens, multiplexación lógica y
seguridad por capacidades integrada, LUMEN reduce la sobrecarga por mensaje en un
64–88%, sostiene millones de mensajes por segundo y transmite tokens con latencia
a escala de microsegundos, manteniéndose interoperable con JSON-RPC mediante un
puente transparente.

El trabajo futuro incluye autenticar el protocolo de acuerdo de claves para
eliminar la suposición de transporte de confianza, formalizar la negociación del
diccionario de sesión para entornos adversariales, extender la evaluación a
despliegues de área amplia y de pasarelas multiinquilino, y estandarizar el
protocolo a través del RFC publicado.

## Agradecimientos

El autor agradece a la comunidad MCP sus comentarios sobre los primeros
borradores del protocolo, y a los autores de las especificaciones e
implementaciones de referencia de Macaroons, CBOR, QUIC y ChaCha20-Poly1305,
sobre las que se construye este trabajo.

## Referencias

[1] Anthropic, «Model Context Protocol Specification».
    https://modelcontextprotocol.io/specification

[2] JSON-RPC Working Group, «JSON-RPC 2.0 Specification».
    https://www.jsonrpc.org/specification

[3] A. Birgisson, J. G. Politz, Ú. Erlingsson, A. Taly, M. Vrable y
    M. Lentczner, «Macaroons: Cookies with Contextual Caveats for
    Decentralized Authorization in the Cloud», en *Proc. NDSS*, 2014.

[4] Y. Nir y A. Langley, «ChaCha20 and Poly1305 for IETF Protocols»,
    RFC 8439, 2018.

[5] A. Langley, M. Hamburg y S. Turner, «Elliptic Curves for Security»,
    RFC 7748, 2016.

[6] H. Krawczyk y P. Eronen, «HMAC-based Extract-and-Expand Key Derivation
    Function (HKDF)», RFC 5869, 2010.

[7] Google, «Protocol Buffers». https://protobuf.dev

[8] C. Bormann y P. Hoffman, «Concise Binary Object Representation (CBOR)»,
    STD 94, RFC 8949, 2020.

[9] J. Iyengar y M. Thomson, eds., «QUIC: A UDP-Based Multiplexed and Secure
    Transport», RFC 9000, 2021.

---

*Este artículo acompaña a la especificación del protocolo LUMEN
(`RFC_LUMEN_ES.md`) y a la referencia para desarrolladores (`SPEC_DEV_ES.md`).
Las implementaciones de referencia están disponibles en
https://github.com/GonzaloMonzonC/lumen-protocol.*
