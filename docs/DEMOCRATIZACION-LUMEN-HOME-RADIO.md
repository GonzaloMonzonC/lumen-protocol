# LUMEN para la democratización de la IA
## Comparativa de encaje · Lumen@Home (voluntariado tipo SETI) · P2P por radio

*17-sep-2026 — Gonzalo Monzón + Hermes. Estado: análisis y arquitectura propuesta (sin implementar).*

---

## 1 · La comparativa de base: qué es YA REAL en un nodo tipo neferu

Antes de soñar, la foto honesta. Un nodo como **neferu** (NAS02, ARMv7, ~4 MB de binario)
hoy hace, verificado en producción:

| Capacidad | Estado | Por qué importa para democratizar |
|---|---|---|
| Binario único ~4 MB (ARMv7 musl) | ✅ vivo | Corre en NAS de desecho, Raspberry, routers. Sin Docker, sin GPU, sin K8s. |
| PDB embebida + rutinas M (texto plano) | ✅ | Todo el estado y la lógica = ficheros legibles, versionables, auditables. |
| LLM gratis con cadena curada y auto-actualizada ($0) | ✅ | La potencia de un asistente sin tarjeta ni suscripción: free-tier consorciado + curador diario. |
| Aislamiento por construcción (config ausente, fail-closed) | ✅ | Seguridad sin muros: lo que no está configurado, no existe. |
| Bridges HTTP + túnel (sin abrir puertos) | ✅ | Publicable desde una red doméstica con una URL. |
| Cron nativo + runners supervisados + work-reports firmados | ✅ | Un nodo que trabaja solo, opina y se deja vigilar. |
| Devices nativos: SSH (fail-closed), HTTP, `llm:call`, RAG | ✅ | La IA es UN device más: sustituible, testeable, perfilable. |
| 5 fuentes de validación escalonadas (hoy) | ✅ | La calidad de la cadena free se mantiene en equipo, no en un datacenter. |
| Macaroons (auth granular por capacidad) | 🟡 existe (31/31 tests) | Permisos delegables sin cuentas centrales. Capa 2 pendiente de despliegue. |
| DDP (transporte nodo↔nodo) | 🟡/✅ | En la privada; apagado por diseño en la pública. |

**Tesis de la comparativa:** la democratización de la IA no es "más GPUs para todos".
Es **nodos pequeños, baratos, autónomos y conectables** — y esta arquitectura ya tiene
construida la mitad (aislamiento, cadena libre, work-units, firmas). Lo que falta no es
potencia: es **red**.

---

## 2 · "Mil cosas": mapa de encaje por caso de uso

| Caso de uso | Ya lo soporta | Falta | Dificultad |
|---|---|---|---|
| Biblioteca viva / ciudad de los libros (neferu) | ✅ 48 voces, 1.275 frases, consola | — | hecho |
| Consola cultural pública (voz, citas, gratis) | ✅ | micro STT | baja |
| Tutor con corpus local (RAG por libro) | ✅/🟡 | interfaces escolares | baja |
| Agente para municipio/ONG (informes, cron, correo) | 🟡 | plantillas + piloto | media |
| Nodo de ciencia ciudadana (validar modelos, curar corpus) | ✅ protocolo base | generalizar work-units | baja |
| **Lumen@Home** (red voluntaria estilo SETI) | 🟡 primitivas listas | spec + onboarding | media |
| Radio comunitaria / off-grid messaging | 🟡 | puente radio + modelo local | media |
| Escuela rural: 1 NAS + WiFi local = aula IA | 🟡 | imagen "todo-en-uno" | media |
| Sensórica / agro (avisos, clima, plagas) | ⚪ | devices serial/MQTT | media |
| Servidor de voz TTS free para colectivos | ✅ edge | despliegue | baja |
| Archivo cultural resiliente (libros, voces, PDB) | ✅ | espejos externos | baja |

Patrón: **lo que aporta soberanía ya funciona; lo que falta es interconexión y empaquetado.**

---

## 3 · Lumen@Home — un SETI@home para nuestra red

### Lo que aprendió SETI@home (1999–2020, 5,2 M voluntarios, 12.000 M detecciones)
- Work units **pequeñas** + cliente **invisible** + **créditos** visibles = millones de PCs donando ciclos.
- BOINC sigue vivo (~30 proyectos): el modelo es sólido si el coste de participar ≈ 0.
- Lección clave: **la comunidad vale más que el cómputo**. Pertenencia > hardware.

### Nuestra versión nace de algo que YA funciona
Los `%ME` de neferu y A **son work units reales**: piden trabajo, ejecutan con límite de gas,
firman el resultado y lo suben a un registro central. Hoy lo hacen 5 fuentes (curador, research,
2 nodos, local, poli). Lumen@Home = **abrir ese mismo circuito a voluntarios**.

### Diseño (reutilizando lo construido)
1. **Unidad de trabajo** `^WORK(id)`: `{tipo, fuente_M, gas, deadline, hash}` firmada por la red.
   Tipos iniciales: validar modelos (ya), minar citas/VOCES de corpus, indexar RAG, tests de
   regresión M, leer y verificar webs (`%WB`/`%WR`), traducir, resumir.
2. **Cliente voluntario**: `mvm-nas --volunteer <url>` — 1 binario, 1 línea, idle-priority.
   Pide trabajo → ejecuta (gas-limit + aislamiento) → firma (HMAC/macaroon) → sube.
3. **Validación**: quórum (2-de-3) para trabajos verificables; reputación simple por nodo.
   Los macaroons ya existen: permiso por *tipo de trabajo* sin cuentas centrales.
4. **Créditos**: contador por nodo (ledger simple, sin blockchain) — ver el propio aporte mueve.
5. **Registro**: `cadences.app` ya es ese rol (KV + API + feed). No hace falta inventarlo.

### Tareas-piloto naturales (por orden de facilidad)
- T1: validar la cadena free desde 100 nodos distintos = 100 franjas horarias/regiones (ya probado con 5).
- T2: minar voces/citas de los 12 libros con quórum (el minero ya existe: `build_voces_rag.py`).
- T3: espejos de PDB entre nodos (resiliencia del archivo).

---

## 4 · P2P por radio — ¿es posible? Sí, por capas (y LUMEN encaja de forma natural)

### Realidad física (sin humo)
| Tecnología | Ancho de banda | Alcance | Notas |
|---|---|---|---|
| LoRa / Meshtastic (ISM 868/915) | ~0,2–20 kbps según preset (LongFast ≈ 1 kbps útil) | km por salto, malla | duty-cycle (~1% en EU868), sin licencia |
| Reticulum (RNS) sobre LoRa/packet/HF/WiFi | la del medio | la del medio | **stack cifrado e2e, "unstoppable networks"**; `rnx`/`rncp` mueven ficheros sobre radio |
| Packet radio VHF / APRS | 1,2–9,6 kbps | decenas de km | clásico, requiere licencia ham para potencia |
| HF (Winlink, JS8Call) | ~pocos kbps | cientos/miles km | propagación ionosférica |
| WiFi AREDN (ham) | Mbps | km | enlaces fijos |

### La observación clave
**Los datos de LUMEN son el caso IDEAL para radio**: las rutinas M son texto de bytes, las
work units y resultados son JSON de KB, las firmas son bytes. **La capa de coordinación
entera — trabajo, resultados, reputación, cadena de modelos — CABE en un canal de 1 kbps.**

Lo que NO viaja por radio: modelos y contenidos grandes. Se quedan locales, se sincronizan
oportunistamente por WiFi cuando lo hay. Y aquí está la pieza que cierra el círculo:

### El nodo 100% autónomo = modelo LOCAL + radio
Añadir un provider `local` al device `llm:call` (Ollama/llama.cpp en la propia NAS, ya soportado
en el diseño del device) convierte cada nodo en autosuficiente: **recibe trabajo por radio,
computa con su modelo local (sin internet), devuelve el resultado por radio.**
Ahí la nube deja de ser necesaria — no por ideología: por física.

### Arquitectura en 3 niveles
```
L0 · RADIO      Reticulum (recomendado) o Meshtastic como transporte
                 (serial↔nododel puente, o UDP si hay IP)
L1 · PUENTE     device "radio:" en el nodo (serial / RNS socket)
                 ↔ PDB / HTTP interno   [mismo patrón que ssh/http/llm]
L2 · LUMEN      work units, DDP, firmas, macaroons  (lo de hoy)
```

### Hardware por nodo
NAS/Pi existente + **módulo LoRa €20–40** (SX1262) o T-Beam/Heltec para nodos móviles.
Sin licencia en bandas ISM (con duty-cycle); ham solo si se quiere HF/potencia.
Repetidores solares para crestas — el patrón de las redes comunitarias reales.

### Hitos propuestos
1. `device radio` en mvm-nas (serial → API local de Meshtastic): **1–2 tardes**.
2. Puente Reticulum (`rncp` para payloads) y prueba neferu ↔ nodo vecino: **2–3 tardes**.
3. Demo end-to-end: neferu emite una work unit por LoRa → nodo vecino la ejecuta (modelo local) → resultado firmado de vuelta: **la primera `%ME` por radio de la historia** 🎯.
4. Lumen@Home sobre radio con relés (solar): la red que sobrevive a la nube.

### Límites honestos
Ancho de banda (KB/s), latencia (store-and-forward), duty-cycle, energía (solar en repetidores),
y que el contenido pesado seguirá necesitando un enchufe cómodo de vez en cuando.

---

## 5 · Cierre: por qué todo esto encaja

- La IA centralizada necesita datacenters. **Esta arquitectura necesita una NAS y una radio de €20.**
- Lo difícil ya está hecho y verificado: aislamiento, cadena libre auto-curada, work-units,
  firmas, registro, cron resiliente, 5 fuentes de validación.
- Lo que falta es **red y empaquetado** — y ambas cosas se construyen por capas, sin apostar nada:
  cada hito es útil por sí mismo (el provider local vale aunque no haya radio; la radio vale
  aunque no haya voluntarios; los voluntarios valen aunque no haya radio).

> **SETI@home buscaba señales de otros. Lumen@Home reparte la inteligencia entre nosotros.**
> Y por radio, si hace falta. 📡

---
*Referencias: Reticulum (markqvist/Reticulum, reticulum.network) · Meshtastic presets ·
SETI@home/BOINC (Berkeley; 5,2 M voluntarios; hibernación 2020) · arquitectura propia:
mvm-nas, nas_bridge, `%ME`/`%ML`, cadences.app (registro), ProjectOS AI Gateway.*
