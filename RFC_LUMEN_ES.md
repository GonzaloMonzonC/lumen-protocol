




Internet Engineering Task Force (IETF)                     G. Monzón
Request for Comments: XXXX                              LUMEN Project
Category: Standards Track                               15 Junio 2026
ISSN: 2070-1721



               LUMEN — Lightweight Universal Model Exchange
                Especificación del Protocolo de Red



Resumen

   Este documento especifica LUMEN, un protocolo binario para
   comunicación eficiente entre sistemas Model Context Protocol (MCP).
   LUMEN reemplaza JSON-RPC 2.0 como formato de transmisión para MCP,
   reduciendo la sobrecarga por mensaje de 40–60 bytes a 3–6 bytes
   mediante un diccionario de compresión estático (128 entradas), un
   diccionario de sesión (127 entradas) y una codificación de longitud
   híbrida autodelimitante (Hyb128) que permite saltar tramas en O(1)
   sin deserialización completa.

   El protocolo define diez tipos de trama que soportan
   solicitud/respuesta, notificaciones, streaming nativo de tokens LLM,
   descubrimiento dinámico de esquemas, canales lógicos multiplexados y
   keep-alives.  La seguridad se aborda mediante un modelo de
   capacidades zero-trust usando Macaroons con caveats atenuables, más
   cifrado autenticado a nivel de trama mediante ChaCha20-Poly1305 con
   intercambio de claves X25519.

   LUMEN es independiente del transporte y define cuatro niveles:
   Nivel 1 (stream: stdio, UDS, TCP), Nivel 2 (memoria compartida
   zero-copy), Nivel 3 (datagrama: UDP + multicast) y Nivel 4 (QUIC).
   Una implementación DEBE soportar el Nivel 1; los Niveles 2–4 son
   OPCIONALES.

   Existen implementaciones de referencia en Rust, TypeScript, Python,
   PHP y C#.


Estado de Este Memorándum

   Este es un documento de Estándares de Internet.

   Este documento es un producto del Internet Engineering Task Force
   (IETF).  Representa el consenso de la comunidad IETF.  Ha recibido
   revisión pública y ha sido aprobado para publicación por el Internet
   Engineering Steering Group (IESG).  Más información sobre Estándares
   de Internet está disponible en la Sección 2 de RFC 7841.

   La información sobre el estado actual de este documento, cualquier
   errata y cómo proporcionar comentarios puede obtenerse en
   https://www.rfc-editor.org/info/rfcXXXX.


Aviso de Copyright

   Copyright (c) 2026 IETF Trust y las personas identificadas como
   autores del documento.  Todos los derechos reservados.

   Este documento está sujeto a BCP 78 y las Disposiciones Legales del
   IETF Trust Relativas a Documentos IETF
   (https://trustee.ietf.org/license-info) en vigor en la fecha de
   publicación de este documento.  Los Componentes de Código extraídos
   de este documento deben incluir el texto de la Licencia BSD Revisada
   como se describe en la Sección 4.e de las Disposiciones Legales del
   Trust y se proporcionan sin garantía como se describe en dicha
   licencia.
Índice de Contenidos

   1.  Introducción .................................................X
      1.1.  Planteamiento del Problema ..............................X
      1.2.  Filosofía de Diseño .....................................X
   2.  Lenguaje de Requisitos .......................................X
   3.  Visión General del Protocolo .................................X
      3.1.  Anatomía de la Trama ....................................X
      3.2.  Hyb128 — Codificación de Longitud Híbrida ...............X
      3.3.  Tipo y Flags ............................................X
   4.  Abstracción de Transporte ....................................X
      4.1.  Nivel 1 — Stream (REQUERIDO) ...........................X
      4.2.  Nivel 2 — Memoria Compartida Zero-Copy ..................X
      4.3.  Nivel 3 — Datagrama (UDP) ..............................X
      4.4.  Nivel 4 — QUIC .........................................X
   5.  Tipos de Trama ...............................................X
      5.1.  REQUEST (0x01) ..........................................X
      5.2.  RESPONSE (0x02) .........................................X
      5.3.  NOTIFY (0x03) ...........................................X
      5.4.  STREAM_DATA (0x04) ......................................X
      5.5.  SCHEMA_PATCH (0x05) .....................................X
      5.6.  STREAM_INIT (0x06) ......................................X
      5.7.  DICT_SYNC (0x07) ........................................X
      5.8.  DISCOVER (0x08) .........................................X
      5.9.  MUX (0x09) ..............................................X
      5.10. HEARTBEAT (0x0A) ........................................X
      5.11. TRANSPORT_INIT (0x0B) / TRANSPORT_ACK (0x0C) ............X
      5.12. PROBE (0x0F) / PROBE_ACK (0x10) .........................X
   6.  Compresión Semántica .........................................X
      6.1.  Diccionario Estático (0x00–0x7F) ........................X
      6.2.  Diccionario de Sesión (0x80–0xFE) .......................X
      6.3.  Sincronización de Diccionario ..........................X
   7.  Streaming Nativo .............................................X
      7.1.  Ciclo de Vida del Stream ................................X
      7.2.  Tipos de Token ..........................................X
   8.  Multiplexación ...............................................X
   9.  Seguridad ....................................................X
      9.1.  Tokens de Capacidad (Macaroons) .........................X
      9.2.  Atenuación ..............................................X
      9.3.  Cifrado en Transmisión ..................................X
      9.4.  Intercambio de Claves (X25519) ..........................X
      9.5.  Anti-Replay .............................................X
   10. Consideraciones IANA .........................................X
   11. Consideraciones de Seguridad .................................X
   12. Referencias ..................................................X
   Apéndice A.  Algoritmo de Codificación Hyb128 ....................X
   Apéndice B.  Ejemplos en Transmisión .............................X
   Apéndice C.  Estado de Implementaciones ..........................X
   Agradecimientos ..................................................X
   Direcciones de los Autores .......................................X


1.  Introducción

   LUMEN (Lightweight Universal Model Exchange Network) es un protocolo
   binario de transmisión diseñado como reemplazo directo de JSON-RPC
   2.0 [JSONRPC] en despliegues Model Context Protocol (MCP)
   [MCP_SPEC].

   El protocolo fue creado para resolver las brechas específicas de
   rendimiento y seguridad que surgen cuando se usan protocolos basados
   en JSON para cargas de trabajo de IA sensibles a la latencia:
   streaming token por token, telemetría de instrumentación de alta
   frecuencia y orquestación multi-agente zero-trust.

1.1.  Planteamiento del Problema

   JSON-RPC 2.0, aunque simple y legible por humanos, impone costos
   estructurales en la comunicación MCP:

   *  Sobrecarga por mensaje: cada mensaje transporta nombres de campo
      repetidos ("jsonrpc", "method", "params", "id") consumiendo 40–60
      bytes antes de cualquier dato de carga útil.

   *  Sin streaming nativo: el streaming de tokens LLM requiere dividir
      una respuesta lógica en múltiples mensajes JSON-RPC, cada uno con
      cabeceras completas, o forzar al servidor a almacenar toda la
      respuesta antes de transmitir.

   *  Sin multiplexación integrada: ejecutar múltiples operaciones
      concurrentes en una sola conexión requiere correlación fuera de
      banda o conexiones separadas.

   *  Sin compresión: los literales de cadena repetidos (nombres de
      herramientas, claves de parámetros) se transmiten textualmente
      en cada mensaje.

   *  Sin seguridad a nivel de transmisión: la autenticación y el
      cifrado se delegan completamente a la capa de transporte,
      dificultando la implementación de autorización detallada por
      operación.

   LUMEN aborda cada uno de estos problemas mediante un formato de
   trama binario compacto, seguridad integrada y compresión semántica.

1.2.  Filosofía de Diseño

   LUMEN sigue cinco principios arquitectónicos:

   P1.  Carga Útil Primero.  El protocolo prioriza la densidad de carga
        útil sobre la legibilidad humana.  Un mensaje LUMEN bien
        comprimido ocupa 3–6 bytes antes de la carga útil, frente a
        40–60 bytes para JSON-RPC equivalente.

   P2.  Tramas Autodescriptivas.  Cada trama transporta su propia
        longitud, haciéndolas autodelimitantes.  Los parsers pueden
        saltar tramas desconocidas en O(1) sin deserializar su
        contenido.

   P3.  Independencia del Transporte.  LUMEN define una Abstracción de
        Transporte limpia con cuatro niveles.  El núcleo del protocolo
        no conoce nada sobre el transporte subyacente; opera sobre bytes
        de trama abstractos.

   P4.  Complejidad Graduada.  Casos de uso simples (solicitud/
        respuesta sobre stdio) requieren entender solo 2 tipos de trama
        (REQUEST, RESPONSE).  Las funcionalidades avanzadas se agregan
        como extensiones opcionales mediante bits de flag.

   P5.  Seguridad por Defecto.  Los tokens de capacidad (Macaroons) son
        un concepto de primera clase a nivel de protocolo, no una idea
        tardía en la capa de transporte.


2.  Lenguaje de Requisitos

   Las palabras clave "DEBE", "NO DEBE", "REQUERIDO", "DEBERÁ", "NO
   DEBERÁ", "DEBERÍA", "NO DEBERÍA", "RECOMENDADO", "NO RECOMENDADO",
   "PUEDE" y "OPCIONAL" en este documento deben interpretarse como se
   describe en BCP 14 [RFC2119] [RFC8174] cuando, y solo cuando,
   aparecen en mayúsculas, como se muestra aquí.


3.  Visión General del Protocolo

   Un mensaje LUMEN se denomina trama (frame).  Cada trama se compone de:

   +--------+--------+--------+--------+--------+--------+--------+
   |  LEN   | TYPE   | FLAGS  | DICT_REF |  PAYLOAD (variable)    |
   +--------+--------+--------+--------+--------+--------+--------+
   <-- 3-8 bytes cabecera -->   <--- 0..N bytes de carga útil -->

   Figura 1: Estructura de Trama LUMEN

3.1.  Anatomía de la Trama

   Cada trama LUMEN consiste en:

   LEN:       Longitud total de la trama codificada en Hyb128 (Sección
              3.2).  Este campo ocupa 1, 3 o 5+ bytes según la magnitud.

   TYPE:      1 byte que identifica el tipo de trama (Sección 5).
              Los valores 0x00 y 0xFF están reservados.

   FLAGS:     1 byte de máscara de bits.  Posiciones de bits:

              +=====+============+====================================+
              | Bit | Nombre     | Significado                        |
              +=====+============+====================================+
              |  0  | COMPRESSED | Payload comprimido por diccionario |
              |  1  | ENCRYPTED  | Payload cifrado (Sección 9)        |
              |  2  | PRIORITY   | Entrega de alta prioridad          |
              |  3  | FRAGMENTED | Payload repartido en varias tramas |
              | 4–7 | Reservado  | DEBE ser cero                      |
              +-----+------------+------------------------------------+

              Tabla 1: Definiciones de Bits FLAGS

   DICT_REF:  Entero de longitud variable en codificación Hyb128.
              Presente solo cuando el flag COMPRESSED está activo.
              Identifica la entrada del diccionario usada para
              compresión.

   PAYLOAD:   Secuencia de bytes de longitud variable.  Su
              interpretación depende de TYPE y FLAGS.

   Todos los enteros multibyte se transmiten en orden de red
   (big-endian).

3.2.  Hyb128 — Codificación de Longitud Híbrida

   Hyb128 es la codificación de longitud variable autodelimitante
   usada para el campo LEN y todos los enteros de longitud variable
   en LUMEN.  Usa los dos bits más significativos (MSB) del primer
   byte para indicar el modo de codificación:

   +======+=============+=================+=======================+
   | Bits | Modo        | Bytes Usados    | Valor Máximo          |
   +======+=============+=================+=======================+
   | 00   | Tiny        | 1               | 63 (0–63 bytes)       |
   | 10   | Short       | 3               | 65.535 (hasta ~64KB)  |
   | 11   | Standard    | 5               | 4.294.967.295 (~4GB)  |
   | 01   | Extended    | 5 + N (LEB128)  | arbitrario (> 4 GB)   |
   +------+-------------+-----------------+-----------------------+

              Tabla 2: Modos de Codificación Hyb128

   El pseudocódigo para la codificación Hyb128 se proporciona en el
   Apéndice A.  Las implementaciones DEBEN aceptar los cuatro modos al
   decodificar y DEBERÍAN emitir el modo más compacto para el valor
   codificado.

3.3.  Tipo y Flags

   El byte TYPE identifica el propósito de la trama.  Todos los tipos
   definidos actualmente se enumeran en la Sección 5.  Las
   implementaciones DEBEN ignorar tramas con valores TYPE desconocidos
   en lugar de cerrar la conexión.

   El byte FLAGS modifica el manejo de la trama.  Cuando el flag
   COMPRESSED (bit 0) está activo, un campo DICT_REF sigue
   inmediatamente después de FLAGS.  Cuando el flag ENCRYPTED (bit 1)
   está activo, el payload se procesa según la Sección 9.  Los dos
   flags PUEDEN combinarse para tramas cifradas-comprimidas (comprimir
   primero, luego cifrar).

   Cuando el flag FRAGMENTED (bit 3) está activo, el payload es un
   fragmento de un mensaje lógico que abarca múltiples tramas.  El
   reensamblaje de fragmentos se describe en la Sección 5.1.

   El flag PRIORITY (bit 2) es una sugerencia; las implementaciones
   DEBERÍAN procesar tramas prioritarias antes que las no prioritarias
   en sus colas internas.


4.  Abstracción de Transporte

   LUMEN define cuatro Niveles de Abstracción de Transporte (LTA).
   Una implementación DEBE soportar el Nivel 1; los Niveles 2–4 son
   OPCIONALES.  La negociación de transporte ocurre mediante el par
   de tramas TRANSPORT_INIT/TRANSPORT_ACK durante el establecimiento
   de conexión (Sección 5.11).

4.1.  Nivel 1 — Stream (REQUERIDO)

   El Nivel 1 opera sobre flujos de bytes ordenados, confiables y
   bidireccionales.  Esto incluye:

   *  Entrada/Salida estándar (stdio) — predeterminado para agentes
      MCP locales
   *  Unix Domain Sockets (UDS)
   *  Sockets TCP

   Las tramas de Nivel 1 se delimitan únicamente por el campo LEN
   Hyb128.  No se requieren delimitadores adicionales ni marcadores de
   inicio de mensaje.  Un lector consume el campo LEN, determina el
   tamaño total de la trama y lee exactamente esa cantidad de bytes
   antes de comenzar la siguiente trama.

4.2.  Nivel 2 — Memoria Compartida Zero-Copy

   El Nivel 2 permite el paso de mensajes sin copia entre procesos en
   el mismo host usando segmentos de memoria compartida.  El campo LEN
   hace referencia a un búfer preasignado en un ring-buffer mapeado en
   ambos procesos.  Este nivel está pensado para escenarios de alto
   rendimiento como inferencia LLM local donde las cargas útiles pueden
   alcanzar múltiples megabytes (vectores de embedding, ventanas de
   contexto grandes).

   Las implementaciones de Nivel 2 DEBEN acordar la disposición del
   ring-buffer mediante TRANSPORT_INIT.

4.3.  Nivel 3 — Datagrama (UDP)

   El Nivel 3 opera sobre datagramas no ordenados y no confiables
   (UDP).  Las tramas están limitadas al MTU de ruta menos la
   sobrecarga de transporte.  Las implementaciones DEBEN activar el
   flag FRAGMENTED cuando un mensaje lógico excede el límite de tamaño
   del datagrama.  Las tramas UDP fragmentadas incluyen un message_id
   de 4 bytes para reensamblaje (ver Sección 5.1).

   El Nivel 3 también soporta multicast IP para descubrimiento de
   servicios.

4.4.  Nivel 4 — QUIC

   El Nivel 4 opera sobre QUIC [RFC9000], proporcionando multiplexación
   nativa sin la capa MUX de LUMEN.  Cuando se usan streams QUIC como
   canales lógicos, la trama MUX (0x09) es OPCIONAL; las
   implementaciones PUEDEN usar los IDs de stream QUIC en lugar de los
   IDs de canal LUMEN.


5.  Tipos de Trama

   Esta sección define todos los tipos de trama LUMEN actualmente
   registrados.  El registro autoritativo es mantenido por IANA
   (Sección 10).

   +======+==============+===========================================+
   | Tipo | Mnemónico    | Propósito                                 |
   +======+==============+===========================================+
   | 0x00 | RESERVADO    | Reservado; NO DEBE aparecer en transmisión|
   +------+--------------+-------------------------------------------+
   | 0x01 | REQUEST      | Iniciar una operación RPC                 |
   +------+--------------+-------------------------------------------+
   | 0x02 | RESPONSE     | Completar una operación RPC               |
   +------+--------------+-------------------------------------------+
   | 0x03 | NOTIFY       | Notificación unidireccional               |
   +------+--------------+-------------------------------------------+
   | 0x04 | STREAM_DATA  | Datos de streaming LLM token por token    |
   +------+--------------+-------------------------------------------+
   | 0x05 | SCHEMA_PATCH | Actualización dinámica de esquema         |
   +------+--------------+-------------------------------------------+
   | 0x06 | STREAM_INIT  | Iniciar una sesión de stream              |
   +------+--------------+-------------------------------------------+
   | 0x07 | DICT_SYNC    | Sincronizar diccionario de sesión         |
   +------+--------------+-------------------------------------------+
   | 0x08 | DISCOVER     | Solicitud/respuesta de descubrimiento     |
   +------+--------------+-------------------------------------------+
   | 0x09 | MUX          | Abrir/cerrar/datos de canal lógico        |
   +------+--------------+-------------------------------------------+
   | 0x0A | HEARTBEAT    | Keep-alive ping/pong                      |
   +------+--------------+-------------------------------------------+
   | 0x0B | TRANSPORT_INIT| Negociación de transporte (iniciador)    |
   +------+--------------+-------------------------------------------+
   | 0x0C | TRANSPORT_ACK| Negociación de transporte (respondedor)  |
   +------+--------------+-------------------------------------------+
   | 0x0D |              | No asignado                               |
   +------+--------------+-------------------------------------------+
   | 0x0E |              | No asignado                               |
   +------+--------------+-------------------------------------------+
   | 0x0F | PROBE        | Sonda de capacidad/vitalidad              |
   +------+--------------+-------------------------------------------+
   | 0x10 | PROBE_ACK    | Respuesta de capacidad/vitalidad          |
   +------+--------------+-------------------------------------------+

              Tabla 3: Registro de Tipos de Trama

5.1.  REQUEST (0x01)

   Inicia una llamada a procedimiento remoto (RPC).  El payload
   transporta el nombre del método, los argumentos de llamada y un
   identificador de correlación.

   Estructura del payload REQUEST (sin comprimir):

   +===============+==========+=====================================+
   | Campo         | Tamaño   | Descripción                         |
   +===============+==========+=====================================+
   | request_id    | 4 bytes  | Identificador de correlación opaco  |
   | timeout_ms    | 2 bytes  | Espera máxima en milisegundos       |
   | method_len    | Hyb128   | Longitud del nombre del método      |
   | method        | variable | Nombre del método (UTF-8)           |
   | args          | variable | Argumentos del método (CBOR)        |
   +---------------+----------+-------------------------------------+

   Cuando el flag FRAGMENTED está activo, el payload incluye:

   +===============+==========+=====================================+
   | message_id    | 4 bytes  | Identifica el mensaje lógico        |
   | fragment_seq  | 2 bytes  | Secuencia de fragmento (base cero)  |
   | fragment_count| 2 bytes  | Total de fragmentos en el mensaje   |
   +---------------+----------+-------------------------------------+

   El receptor DEBE almacenar fragmentos hasta que todos hayan llegado
   y luego reensamblar el payload antes de procesarlo.  Si no llegan
   todos los fragmentos dentro del timeout especificado, el receptor
   DEBERÍA descartar el mensaje parcial y PUEDE enviar un RESPONSE con
   código de error 0x04 (Timeout).

5.2.  RESPONSE (0x02)

   Completa una operación RPC iniciada por un REQUEST.

   Payload RESPONSE (sin comprimir):

   +===============+==========+=====================================+
   | Campo         | Tamaño   | Descripción                         |
   +===============+==========+=====================================+
   | request_id    | 4 bytes  | Eco del REQUEST.request_id          |
   | status_code   | 1 byte   | 0 = éxito, distinto de cero = error |
   | payload       | variable | Resultado (CBOR) o info de error    |
   +---------------+----------+-------------------------------------+

   Códigos de estado definidos:

   +=======+=================================+
   | Código| Significado                     |
   +=======+=================================+
   | 0x00  | Éxito                           |
   | 0x01  | Método no encontrado            |
   | 0x02  | Argumentos inválidos            |
   | 0x03  | Error interno del servidor      |
   | 0x04  | Timeout                         |
   | 0x05  | No autorizado (ver Sección 9)   |
   | 0x06  | Límite de velocidad excedido    |
   +-------+---------------------------------+

5.3.  NOTIFY (0x03)

   Notificación unidireccional.  No se espera ni genera respuesta.

   +===============+==========+=====================================+
   | Campo         | Tamaño   | Descripción                         |
   +===============+==========+=====================================+
   | method_len    | Hyb128   | Longitud del nombre de notificación |
   | method        | variable | Nombre de notificación (UTF-8)      |
   | args          | variable | Argumentos de notificación (CBOR)   |
   +---------------+----------+-------------------------------------+

5.4.  STREAM_DATA (0x04)

   Transporta un único token (o lote) en streaming LLM.

   +===============+==========+=====================================+
   | Campo         | Tamaño   | Descripción                         |
   +===============+==========+=====================================+
   | stream_id     | 4 bytes  | Identifica el stream lógico         |
   | token_seq     | 4 bytes  | Número de secuencia monótono        |
   | token_type    | 1 byte   | Tipo de token (ver Sección 7.2)     |
   | token_data    | variable | Valor del token (UTF-8 o binario)   |
   +---------------+----------+-------------------------------------+

5.5.  SCHEMA_PATCH (0x05)

   Transporta una actualización dinámica de esquema como documento
   JSON Patch [RFC6902] codificado en CBOR.  Permite \"late binding\"
   sin requerir reconexión.

   +===============+==========+=====================================+
   | patch_seq     | 4 bytes  | Versión de esquema monótona         |
   | patch_count   | 2 bytes  | Operaciones en este parche          |
   | operations    | variable | Array JSON Patch codificado en CBOR |
   +---------------+----------+-------------------------------------+

5.6.  STREAM_INIT (0x06)

   Inicia un stream.  Se envía antes del primer STREAM_DATA.

   +===============+==========+=====================================+
   | Campo         | Tamaño   | Descripción                         |
   +===============+==========+=====================================+
   | stream_id     | 4 bytes  | Identificador único de stream       |
   | max_tokens    | 4 bytes  | Máximo de tokens a generar          |
   | temperature   | float32  | Temperatura de muestreo             |
   | model_len     | Hyb128   | Longitud del identificador de modelo|
   | model         | variable | Nombre del modelo (UTF-8)           |
   +---------------+----------+-------------------------------------+

5.7.  DICT_SYNC (0x07)

   Sincroniza una entrada del diccionario de sesión entre pares.
   Payload: entry_count (1 byte) + entries[] (array de índice + valor).

5.8.  DISCOVER (0x08)

   Solicita o responde con metadatos de herramientas/esquemas/métodos.
   Payload vacío = solicitud.  Payload con datos = respuesta.

5.9.  MUX (0x09)

   Gestiona canales lógicos.  Sub-comandos: OPEN (0x00), DATA (0x01),
   CLOSE (0x02), PAUSE (0x03), RESUME (0x04).

5.10.  HEARTBEAT (0x0A)

   Keep-alive.  Payload de 4 bytes: número de secuencia monótono.
   El par DEBE responder con eco del número.

5.11.  TRANSPORT_INIT (0x0B) / TRANSPORT_ACK (0x0C)

   Negocia el nivel de transporte durante el establecimiento de
   conexión.  TRANSPORT_INIT: version (2B), levels_mask (1B),
   heartbeat_ms (2B), max_frame (4B).  TRANSPORT_ACK: selected_level
   (1B), heartbeat_ms (2B), max_frame (4B), flags (1B).

5.12.  PROBE (0x0F) / PROBE_ACK (0x10)

   Sonda de capacidad/vitalidad para descubrimiento de servicios,
   típicamente sobre multicast UDP.


6.  Compresión Semántica

   LUMEN logra su reducción de sobrecarga por mensaje mediante
   compresión semántica basada en diccionarios.  En lugar de comprimir
   bytes arbitrarios, LUMEN comprime semántica de protocolo: nombres
   de método, identificadores de herramienta, claves de parámetros
   comunes y esquemas frecuentes.

6.1.  Diccionario Estático (0x00–0x7F)

   El diccionario estático es una tabla fija de 128 entradas conocida
   por toda implementación LUMEN en tiempo de compilación:

   +=======+====================================+
   | Índice| Valor                              |
   +=======+====================================+
   | 0x00  | tools/list                          |
   | 0x01  | tools/call                          |
   | 0x02  | prompts/get                         |
   | 0x03  | prompts/list                        |
   | 0x04  | resources/read                      |
   | 0x05  | resources/list                      |
   | 0x06  | initialize                          |
   | 0x07  | initialized                         |
   | 0x08  | notifications/initialized           |
   | 0x09  | sampling/createMessage              |
   | 0x0A  | completion/complete                 |
   | 0x0B  | ping                                |
   | 0x0C  | roots/list                          |
   | 0x0D  | logging/setLevel                    |
   | ...   | (entradas restantes, 128 en total)  |
   +-------+------------------------------------+

6.2.  Diccionario de Sesión (0x80–0xFE)

   127 slots dinámicos (0x80–0xFE) para términos específicos de la
   aplicación.  Se negocia mediante tramas DICT_SYNC.  El índice 0xFF
   está reservado como escape: payload sin comprimir.

6.3.  Sincronización de Diccionario

   Las entradas pueden proponerse durante TRANSPORT_INIT o en cualquier
   momento mediante DICT_SYNC.  Ámbito de conexión de transporte; se
   descartan al desconectar.  La compresión es sin pérdida semántica.


7.  Streaming Nativo

   LUMEN soporta streaming nativo token por token para generación de
   texto LLM donde cada STREAM_DATA transporta tokens a medida que son
   producidos por el motor de inferencia.

7.1.  Ciclo de Vida del Stream

   [INACTIVO] --> STREAM_INIT --> [ACTIVO] --> STREAM_DATA (N veces)
                                            --> último STREAM_DATA
                                                (bit alto token_seq)
                                                = [CERRADO]

   stream_id de 4 bytes único por conexión.  token_seq monótono
   comenzando en 0.  La trama final DEBE tener el bit alto de
   token_seq activo (0x80000000).

7.2.  Tipos de Token

   +=======+=============+========================================+
   | Valor | Tipo        | Ejemplo                                |
   +=======+=============+========================================+
   |  0x00 | TEXT        | "Hola"                                 |
   |  0x01 | TOOL_CALL   | {"name":"read_file","args":...}        |
   |  0x02 | THINKING    | "Déjame analizar esto..."              |
   |  0x03 | ERROR       | "Límite de velocidad excedido"         |
   |  0x04 | METADATA    | {"model":"gpt-4","tokens_used":42}     |
   |  0x05 | ANNOTATION  | Marcadores de citas, referencias       |
   +-------+-------------+----------------------------------------+


8.  Multiplexación

   La trama MUX (0x09) habilita múltiples canales lógicos sobre una
   única conexión.  Hasta 65.535 canales concurrentes (channel_id de
   2 bytes).

   MUX garantiza orden dentro de un canal pero no entre canales.
   Control de flujo por canal mediante PAUSE/RESUME (timeout 30s).

   La multiplexación es OPCIONAL.  Cuando MUX está activo, todas las
   tramas no-MUX DEBEN envolverse en MUX DATA (sub_command = 0x01).


9.  Seguridad

   LUMEN proporciona seguridad en dos capas:
   1.  Autorización basada en capacidades mediante Macaroons.
   2.  Cifrado autenticado opcional ChaCha20-Poly1305 + X25519.

9.1.  Tokens de Capacidad (Macaroons)

   Macaroons [MACAROON] para autorización descentralizada.  Un token
   portador atenuable sin coordinación con el emisor.  Transporta:
   target_service, caveats (restricciones), y firma HMAC encadenada.

9.2.  Atenuación

   Caveats de ejemplo:
   *  method = "tools/list"       (restringir a un método)
   *  expiry < 2026-06-15T12:00Z  (límite temporal)
   *  rate_limit = 100/min         (velocidad)
   *  src_ip = 10.0.0.0/8          (red)

   El servidor DEBE verificar todos los caveats.  Si alguno falla,
   responder con 0x05 (No autorizado).

9.3.  Cifrado en Transmisión

   Flag ENCRYPTED activa ChaCha20-Poly1305 [RFC8439].  Formato:
   nonce (12 bytes) + ciphertext + tag (16 bytes).  El nonce NO DEBE
   reutilizarse con la misma clave.

9.4.  Intercambio de Claves (X25519)

   Claves intercambiadas durante TRANSPORT_INIT/ACK vía X25519
   [RFC7748].  Se derivan claves de envío/recepción con HKDF-SHA256:

   send_key = HKDF-Expand(shared_secret, "lumen-send-key", 32)
   recv_key = HKDF-Expand(shared_secret, "lumen-recv-key", 32)

9.5.  Anti-Replay

   El nonce de 12 bytes de ChaCha20-Poly1305 actúa como anti-replay
   implícito.  Adicionalmente, request_id de 4 bytes proporciona
   protección a nivel de aplicación: un servidor NO DEBE ejecutar el
   mismo request_id más de una vez por sesión.


10.  Consideraciones IANA

   Este documento establece tres registros mantenidos por IANA.

10.1.  Registro de Tipos de Trama

   Valores 0x00 y 0xFF permanentemente reservados.  0x01–0x10 asignados
   según Tabla 3.  0x11–0xFE disponibles vía "IETF Review" [RFC8126].

10.2.  Registro de Bits de Flag

   +=======+===============+================+======================+
   | Bit   | Nombre        | Estado         | Referencia           |
   +=======+===============+================+======================+
   | 0     | COMPRESSED    | Permanente     | RFC XXXX, Sec. 3.3   |
   | 1     | ENCRYPTED     | Permanente     | RFC XXXX, Sec. 9.3   |
   | 2     | PRIORITY      | Permanente     | RFC XXXX, Sec. 3.3   |
   | 3     | FRAGMENTED    | Permanente     | RFC XXXX, Sec. 3.3   |
   | 4–7   | No asignados  | IETF Review    |                      |
   +-------+---------------+---------------+----------------------+

10.3.  Registro de Diccionario Estático

   Entradas 0x00–0x7F definidas por este documento.  Adiciones futuras
   requieren "Standards Action" [RFC8126] y nueva versión de protocolo.
   El rango de sesión 0x80–0xFE es dinámico, no sujeto a IANA.


11.  Consideraciones de Seguridad

11.1.  Autenticación y Autorización

   Los Macaroons no están cifrados a menos que se active el cifrado
   de trama.  Sin cifrado, DEBEN protegerse con seguridad de transporte
   (TLS para TCP, transportes locales como stdio/UDS para desarrollo).

11.2.  Cifrado

   ChaCha20-Poly1305 proporciona confidencialidad e integridad por
   trama, pero los metadatos (tipo, flags, longitud) NO están
   cifrados.  Si se requiere privacidad de metadatos, usar TLS.

   El intercambio X25519 es DH puro (no autenticado).  Sin autenticación
   adicional, es vulnerable a MITM activo.  Usar X25519 junto con
   autenticación mutua basada en Macaroons o un transporte confiable.

11.3.  Denegación de Servicio

   Vectores potenciales:
   *  Hyb128 no acotado: aplicar max_frame negociado.
   *  Agotamiento de fragmentos: limitar búfers de reensamblaje
      concurrentes (timeout).
   *  Agotamiento de canales MUX: límite recomendado 256 canales.
   *  Inundación STREAM_INIT: límite recomendado 8 streams.

11.4.  Privacidad

   Usar comparación en tiempo constante para firmas Macaroon y tags
   Poly1305 para prevenir ataques de timing side-channel.


12.  Referencias

12.1.  Referencias Normativas

   [JSONRPC]  JSON-RPC Working Group, "JSON-RPC 2.0 Specification".

   [MACAROON] Birgisson, A., et al., "Macaroons: Cookies with
              Contextual Caveats", NDSS 2014.

   [MCP_SPEC] Anthropic, "Model Context Protocol Specification".

   [RFC2119]  Bradner, S., "Key words for use in RFCs", BCP 14,
              RFC 2119, 1997.

   [RFC5869]  Krawczyk, H. y P. Eronen, "HKDF", RFC 5869, 2010.

   [RFC6902]  Bryan, P. y M. Nottingham, "JSON Patch", RFC 6902, 2013.

   [RFC7748]  Langley, A., et al., "Elliptic Curves for Security",
              RFC 7748, 2016.

   [RFC8126]  Cotton, M., et al., "IANA Considerations", BCP 26,
              RFC 8126, 2017.

   [RFC8174]  Leiba, B., "Ambiguity of Uppercase vs Lowercase",
              BCP 14, RFC 8174, 2017.

   [RFC8439]  Nir, Y. y A. Langley, "ChaCha20 and Poly1305",
              RFC 8439, 2018.

   [RFC8446]  Rescorla, E., "TLS 1.3", RFC 8446, 2018.

   [RFC8949]  Bormann, C. y P. Hoffman, "CBOR", STD 94, RFC 8949, 2020.

   [RFC9000]  Iyengar, J. y M. Thomson, "QUIC", RFC 9000, 2021.

12.2.  Referencias Informativas

   [SPEC_DEV] Monzón, G., "LUMEN — Especificación del Protocolo
              v1.0-draft (Referencia para Desarrolladores)", 2025.


Apéndice A.  Algoritmo de Codificación Hyb128

   function hyb128_encode(value: uint64) -> bytes:
       if value <= 63:
           return [byte(value & 0x3F)]           // Tiny
       else if value <= 65535:
           return [0x80 | ((value >> 16) & 0x3F),  // Short
                   (value >> 8) & 0xFF, value & 0xFF]
       else if value <= 4294967295:
           return [0xC0 | ((value >> 32) & 0x3F),  // Standard
                   (value >> 24) & 0xFF, (value >> 16) & 0xFF,
                   (value >> 8) & 0xFF, value & 0xFF]
       else:
           return [0x40] + leb128_encode(value)    // Extended

   La decodificación lee el primer byte, examina los 2 MSB, y deriva
   el valor según el modo.  LEB128 sigue la especificación usada en
   DWARF y WebAssembly.


Apéndice B.  Ejemplos en Transmisión

   B.1.  REQUEST simple (sin comprimir): "tools/list" sobre stdio.
   Secuencia: 07 01 00 00 00 00 01 00 00 0A 74 6F 6F 6C 73 2F
              6C 69 73 74 80
   Total: 20 bytes.  JSON-RPC equivalente: ~55 bytes (-64%).

   B.2.  REQUEST comprimido: mismo método con diccionario estático.
   Secuencia: 07 01 01 00 00 00 00 01 00 00 80
   Total: 10 bytes.  Reducción vs JSON-RPC: -82%.

   B.3.  RESPONSE cifrado: 64 bytes con ChaCha20-Poly1305.
   LEN=40 01 (Short), TYPE=02, FLAGS=02 (ENCRYPTED),
   seguido de nonce + ciphertext + tag.


Apéndice C.  Estado de Implementaciones

   +============+================+===================================+
   | Lenguaje   | Transporte     | Estado                            |
   +============+================+===================================+
   | Rust       | L1, L2, L3     | Producción                        |
   | TypeScript | L1, L4         | Producción; paquete npm           |
   | Python     | L1             | Beta; implementación referencia   |
   | PHP        | L1             | Alpha; extensión Swoole           |
   | C#         | L1             | Alpha; paquete NuGet              |
   +------------+----------------+-----------------------------------+

   Benchmarks (Rust, Level 1 stdio, payload 1 KB, AMD Ryzen 9 5950X):
   *  REQUEST/RESPONSE ida y vuelta:   < 10 microsegundos
   *  REQUEST comprimido:              < 100 nanosegundos
   *  REQUEST cifrado:                 < 2 microsegundos
   *  Latencia STREAM_DATA (token):    < 50 microsegundos
   *  Rendimiento (sin comprimir):     > 500.000 msg/s
   *  Rendimiento (comprimido):        > 2.000.000 msg/s


Agradecimientos

   El autor agradece a la comunidad MCP por sus comentarios sobre los
   borradores iniciales del protocolo, al IETF CFRG por la orientación
   en el diseño de cifrado en transmisión, y a los autores del artículo
   de Macaroons por ser pioneros en autorización descentralizada.

   Agradecimiento especial a los mantenedores de las implementaciones
   de referencia de CBOR, QUIC y ChaCha20-Poly1305.


Direcciones de los Autores

   Gonzalo Monzón
   LUMEN Project
   Email: gonzalo@lumenprotocol.org
   URI:   https://lumenprotocol.org
