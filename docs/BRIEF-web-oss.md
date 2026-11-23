# Brief — Rediseño de lumen.cadences.app como sitio oficial OSS de lumen-protocol

> Documento de traspaso. Preparado el 22-nov-2026 al cerrar sesión.
> **No hay decisiones tomadas.** Recoge datos verificados, hallazgos y opciones
> para que la próxima sesión decida con criterio, no para ejecutar a ciegas.

---

## 1. Qué pidió Gonzalo (literal)

> "Deberíamos revisar el contenido de la página principal de lumen.cadences.app.
> Es el website del repo oficial lumen-protocol, y diría que no está a la altura.
> Revisa el README principal: hace mención a CASOS_USO_AGENTES.md y debería salir
> ese doc pero en inglés, no sé si lo tenemos. Y luego como página principal lo que
> tenemos en lumen.cadences.app no me gusta mucho. Estaría bien dejarlo como una
> sección... /agentes, /agentes/demo no sé. Pero en la web de un sitio OSS como
> lumen-protocol deberíamos... hay que investigar bien, habría que fijarse en
> páginas de repositorios similares a ver qué suelen poner en la web y luego
> decidir si solo añadir contenido a lo actual, o rehacerlo. Sobre el tema de chat
> con agentes, como tenemos ecos.cadenceslab.com, no es necesario."

Preguntas abiertas que dejó:
1. ¿Añadir a lo actual, rehacer, o reestructurar?
2. ¿Qué se libera más de LUMEN (OSS) y qué queda en ECOS (propietario)?

---

## 2. Hallazgos verificados

### 2.1 El doc enlazado está en español
`README.md` (en inglés, líneas 246 y 364) apunta a
`docs/CASOS_USO_AGENTES.md`, y ese documento **está en español** (25 KB).

Es un fallo de coherencia real: un lector inglés que pulsa el enlace
aterriza en otro idioma.

**Opciones:**
- Traducirlo a `docs/AGENT_USE_CASES.md` (en) y mantener el español como
  `CASOS_USO_AGENTES.es.md`.
- Traducirlo y dejar solo inglés (pierde al lector hispanohablante).
- Lo mismo aplica a los otros ~44 docs de `docs/`, muchos en español.

**Pendiente de decidir:** ¿cuál es el idioma de referencia del proyecto?
El README está en inglés, los docs mayoritariamente en español. Hay que
elegir una política y aplicarla, no dejar la mezcla.

### 2.2 El README tiene 396 líneas y 14 secciones
```
🌍 Why LUMEN exists — the three bets
Why?
Quick Start
Protocol in one diagram
Key metrics
Implementations
MCP Servers
🧠 Your Personal Assistant with Cognitive Superpowers
🧠 The Cognitive OS — agents that build their own system
Transport levels
Hermes Agent Integration
Status & Roadmap
Docs
License
```
Es un README **completo**, casi un documento de producto. Eso es relevante:
la web no debería repetirlo, debería **resumirlo y enlazarlo**.

### 2.3 Estado actual de la web (`lumen-site`, desplegada en lumen.cadences.app)
- `/` — posicionamiento "Un agente es una fila, no una clase". Buena tesis,
  pero es **una landing de producto**, no un sitio de proyecto OSS.
- `/demo/` — 20 agentes en el navegador (WASM). Funciona.
- `/console/` — panel de operación de la MVM. Funciona.

Problema de fondo: **el sitio vende** (landing comercial) cuando debería
**explicar y documentar** (sitio de proyecto abierto). Son registros distintos.

### 2.4 Lo que hacen los proyectos OSS de referencia (investigado)
Patrones que se repiten en webs de proyectos OSS consolidados:

| Elemento | Por qué está |
|---|---|
| **Hero con la propuesta en una frase** | Qué es, en 5 segundos |
| **Instalación en 1-2 líneas** (`npm i`, `cargo add`, `docker run`) | Lo primero que busca un dev |
| **Demo o GIF funcionando** | Prueba antes de instalar |
| **Features en 3-4 bloques cortos** | Escaneable, no un muro |
| **Enlaces a docs / API / ejemplos** | El sitio no documenta: deriva |
| **Quién lo usa / casos reales** | Confianza |
| **Estado del proyecto** (versión, licencia, CI, roadmap) | Señal de salud |
| **Cómo contribuir** | Es un proyecto abierto, no un producto |

Fuentes consultadas: patrón Docusaurus/GitBook/Mintlify para docs;
anatomía de landings OSS (Strapi); ejemplos de frameworks de agentes
(GraphBit, HAMLET, Bunshin) — todos con la misma estructura:
**hero → install → features → docs → contribuir**.

### 2.5 Lo que NO debe ir en la web OSS
- Chat con agentes en vivo → ya existe en **ecos.cadenceslab.com** (propietario).
  Gonzalo lo descartó explícitamente.
- Tono comercial, superlativos, comparativas con otros frameworks.

---

## 3. La tensión de fondo: LUMEN (OSS) vs ECOS (propietario)

Esto salió en conversaciones anteriores y **no está resuelto**:

- **ECOS** = Edge Cognitive OS. Producto propietario. Tiene su web con chat.
- **LUMEN / lumen-protocol** = el motor, el protocolo, las rutinas. Es lo abierto.

**Pregunta abierta:** qué se libera.
- ¿Todo el motor y las rutinas base? (ya está en el repo, MIT)
- ¿Los agentes de referencia (astrid, elena, iris, lumi)? ¿Algunos?
- ¿El stack cognitivo completo (PDB, DDP, MVM)? ¿O parte queda en ECOS?
- ¿Dónde queda la frontera exacta entre "lo que regalas" y "lo que vendes"?

Sin esta respuesta, la web no puede decir con honestidad qué es OSS.

---

## 4. Opciones para la web (sin decidir)

### Opción A — Añadir contenido a lo actual
Conservar `/` como está y añadir `/docs`, `/agentes`, `/roadmap`.
- **Pro:** rápido, no rompe nada.
- **Contra:** el hero sigue siendo comercial; no resuelve el registro.

### Opción B — Reestructurar en secciones
Mantener el diseño pero reorganizar el sitio como web de proyecto:
```
/                    hero + qué es + install de 2 líneas + enlaces
/agentes             los 20 agentes (tabla navegable) + demo
/agentes/demo        la demo actual
/console             el panel actual
/docs                índice de documentación
/docs/<doc>          los docs renderizados
/roadmap             estado y próximos pasos
/contribuir          cómo participar
```
- **Pro:** conserva lo que funciona, cambia el rol de la home.
- **Contra:** hay que escribir la home de nuevo igualmente.

### Opción C — Rehacer con generador de docs (Docusaurus / Astro Starlight)
- **Pro:** navegación, búsqueda y versionado de docs gratis; es lo estándar.
- **Contra:** más peso, otra herramienta que mantener; la demo WASM hay que
  encajarla aparte.

---

## 5. Datos técnicos útiles para la próxima sesión

- Repo: `~/Documents/GitHub/lumen-protocol` (público, MIT)
- Web: `~/Documents/GitHub/lumen-site` → Cloudflare Pages, proyecto `lumen`
- Desplegar: `npx wrangler pages deploy site --project-name=lumen`
- Docs: 45 ficheros en `docs/`, mayoría en español
- README: 396 líneas, inglés
- Demo: 20 agentes, 444 KB gzip, verificado en producción
- Consola: panel de operación, verificado en producción
- Proxy LLM: `functions/api/llm.js`, clave en secret, 11 modelos `:free` en cascada

---

## 6. Lo que hay que decidir antes de escribir una línea de código

1. **¿Idioma del proyecto?** ¿Inglés como referencia y español traducido, o al revés?
2. **¿Qué se libera y qué queda propietario?** La frontera LUMEN/ECOS.
3. **¿Opción A, B o C?** Añadir, reestructurar o rehacer con generador.
4. **¿La demo se queda en la home o se mueve a `/agentes/demo`?**
5. **¿El tono es "proyecto abierto" o "producto"?** Cambia todo el copy.

Con esas cinco respuestas, el trabajo es mecánico.

---

## 7. Nota de método

Gonzalo prefiere: variantes rotando antes de programar, respuestas llanas,
sin lenguaje negativo, y datos reales nunca placeholders. El sitio debe leerse
como algo que alguien **usa**, no como algo que alguien **vende**.
