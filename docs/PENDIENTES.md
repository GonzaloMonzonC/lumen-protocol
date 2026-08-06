# PENDIENTES — Ecosistema Cadences Lab

## P1. Duplicación de instancias de poli_server por sesión (ALTA)

**Problema detectado**: 2026-08-05 — hay 4 procesos `poli_server.py` corriendo a la vez
(Python313, venv, uv). Cada sesión nueva del gateway parece lanzar una instancia nueva
del MCP server de Poli en vez de conectarse a la existente.

**Impacto**: memoria desperdiciada, estado fragmentado entre instancias, respuestas
cacheadas de sesiones anteriores.

**RESUELTO 2026-08-06 (madrugada)**: diagnóstico real — cada reinicio del gateway lanza
un par de MCP servers nuevo (venv+uv) y los anteriores quedan huérfanos (el gateway
muerto no mata a sus hijos). Se encontraron 11 procesos acumulados de 6 arranques.
Limpieza: matados los 9 huérfanos (quedan los 2 del gateway actual). El gateway relanza
sus MCP automáticamente al detectar la muerte de los suyos (verificado: poli responde,
351 modos). Prevención: `restart_gateway.py` ahora ejecuta `cleanup_orphan_mcp()` antes
de relanzar (mata poli_server de gateways muertos). Pendiente opcional: investigar por
qué el MCP manager lanza 2 procesos (venv+uv) por gateway — probablemente dos entradas
de config o dos perfiles; no bloquea pero conviene entenderlo.

**Investigación pendiente**:
- ¿Cómo lanza el MCP manager de Hermes los servers stdio? ¿Por sesión o por proceso?
- ¿`poli_server.py` debería correr como daemon único con transporte lumen/SHM en vez
  de stdio por sesión?
- Ver si hay config para compartir instancia (`mcp_servers` → reuse / singleton)
- Ver el watchdog de Poli (¿existe? ¿relanza instancias?): `watchdog_fabella.py` solo
  cubre el bridge MTProto

**RECURRENCIA 2026-08-06 (tarde)**: vuelve a haber 5 `poli_server.py` vivos
(11244, 15284, 2484, 11820, 14696) pese al cleanup. Síntoma nuevo: el HTTP de Poli
en :8082 lo atiende un proceso duplicado que devuelve SIEMPRE la misma respuesta
cacheada en `/v1/chat` (ignora mensajes y sesiones nuevas); el canal MCP habla con
otro proceso y funciona. → La duplicación vuelve a acumularse; el cleanup del
`restart_gateway.py` no cubre relanzamientos intermedios. (registrado con Angi)

**Solución deseada**: 1 instancia de Poli. Cuando llega una sesión nueva, hablar con el
Poli activo (mismo proceso), no crear uno nuevo.

**Referencia**: `config.yaml` → `mcp_servers.poli` ; `poli_server.py` → `_STATE`

---

## P5. Router de keywords de poli_chat con folding de acentos (MEDIA)

**Problema detectado**: 2026-08-06 — el mensaje "Decision clave" (sin acento) disparó
la rama DECISIONS de `tool_poli_chat` porque "decision" es el fold ASCII de
"decisión" → creó un `dec_` fantasma (dec_1785985350). La detección de keywords
normaliza acentos pero no exige límites de palabra, así que cualquier palabra que
contenga el fold de una keyword (decision, estado, piensa, guarda...) secuestra la
conversación.

**Fix propuesto**: normalizar texto Y keywords a ASCII, y exigir límites de palabra
(expresiones tipo `\bkeyword\b`) o al menos que el match no sea substring de una
palabra más larga con sentido distinto.

**Workaround mientras tanto**: escanear el mensaje normalizado a ASCII contra las
keywords antes de enviar; reformular ("Eleccion de diseno" en vez de "Decision clave").

---

## P2. Timeout de Smith multi-asesor (>300s) (ALTA)

**Problema detectado**: 2026-08-05 — Smith con 2+ asesores del gabinete (fibras LLM
paralelas + síntesis) excede el timeout de 300s del MCP server. Con 1 asesor responde
bien (~30-60s). La primera prueba multi-asesor (vega+pamies) dio TimeoutError de 300s.

**Veredicto del equipo** (Tom + Campo + Angi, 2026-08-05):
- NO parchear timeout, NO limitar asesores (baja calidad del consejo), NO reducir
  timeout de LLMs (degrada calidad).
- Solución: **ACK temprano + asíncrono** — el MCP responde al instante `202 + job_id`,
  las fibras corren en background, entrega posterior (consulta `/status/{job_id}` o
  aviso al chat cuando la síntesis esté lista).
- **Streaming con feedback parcial** (Campo): opción para UX ("asesor 1 listo, asesor 2
  deliberando") con heartbeats; SHM ya acumula resultados parciales; Zalo puede emitir
  eventos de progreso. Plan B = async puro.
- Cambio acotado al adaptador MCP de Poli, sin tocar el núcleo de Smith ni el gateway.

**Pendiente**: decidir streaming vs async puro tras medir coste de habilitar streaming.

**Estado 2026-08-05 (noche)**: P3 (síntesis rota) RESUELTO — los partials se escriben en
globals M por trozos (^SYNTH(n)) y se referencian con $G() en vez de incrustar el prompt
gigante en el src M. Commit 2fad84a. Prueba multi-asesor (pamies+porto+vega) devolvió
síntesis unificada completa con puntos comunes, tensiones y contribuciones. El timeout
no apareció en la prueba. Mejora menor (P4): el sintetizador renombra a los asesores
como roles genéricos en vez de mantener los nombres del gabinete — ajustar el prompt de
síntesis para conservar las etiquetas reales (pamies/porto/vega).

**ESTRÉS SUPERADO 2026-08-05 (noche)**: 3 rondas simultáneas (pamies+porto+vega,
roberto+javier, mixta con Sina) — todas con síntesis OK, sin timeouts, sin huérfanos
en ^SYNTH (0 en dump), límite 3 asesores respetado (R3 detectó 5, ejecutó 3). El consejo
delibera en paralelo y sintetiza de forma robusta. Próximo (Fase 1 de Zalo): suite de
pruebas formales en ^KANBAN registrando inputs, vectores, partials, orden de síntesis
y score de coherencia antes de abrir Poli a más personalidades.

**P4 RESUELTO + BUG SÍNTESIS ENCONTRADO 2026-08-05 (noche)**: 
- P4 (etiquetas reales): el prompt de síntesis inyecta las etiquetas dinámicas del
  gabinete (real_labels) como reglas obligatorias — commit 96466ae. Validado: la síntesis
  conserva [🏗️ Roberto], [🤝 Javier], etc.
- BUG: los partials no llegaban al sintetizador (pedía "las aportaciones"). Causa raíz
  PROBADA en el MVM: un SET M con salto de línea real falla (ok:false, execution:error).
  Los partials con markdown multi-línea rompían S ^SYNTH(n) → $G() vacío → prompt sin
  aportaciones. Fix: reemplazar \n/\r por espacios al escribir los trozos — commit 825afa9.
  Validado: síntesis completa con aportaciones + etiquetas reales integradas.

---

## Registro de jornadas

### 2026-08-05 (tarde-noche)
- **Estabilización Telegram**: gateway relanzado limpio (PID 5920, polling mode, 52 cmd).
  Causa de la caída: reinicio del gateway a las 22:09 que no volvió a levantarse solo.
  Bridge único gestionado por watchdog_fabella (:8086/:8087). Cola de updates vaciada.
  Lección: al reiniciar el gateway hay que verificar que vuelve (arranque manual si no).
- **LUMEN MCP**: fix config `lumen_thinking` → `server.py` + `transport: stdio` (server_native
  no respondía al handshake JSON-RPC). 81 tools montadas vía lumen-shm-bridge.
- **Personalidades MVM**: creadas pamies (finanzas/datos), porto (IA/fullstack) desde perfiles
  reales del repo cadenceslab. Vega (volatilidad/dispersión) creada tras autopsia de Poli.
- **Autopsia real** (5 acciones) → critical_rules ajustadas de roberto/javier/pamies/porto.
- **SMITH CONSEJO**: routing del gabinete en `^SMITH("routing",dominio)=asesor`, reglas
  (max_asesores=3, umbral=0.6, default=poli, consejo_conciliado=1, fibras_paralelas=1).
- `poli_server.py` actualizado: routing del gabinete + labels (commit 2878e7b).
- Wiki Poli: "PERSONALIDADES INTERNAS" + "SMITH CONSEJO".
- Push: lumen-protocol 5002544→2878e7b→13dc967; cadenceslab-social 037fba3.
- Prueba de detección de dominios: 6/6 OK (roberto, javier, pamies, porto, vega, default poli).
- Pendiente verificación en vivo: Smith con código nuevo tras reinicio del gateway (el MCP
  server de Poli se relanza con el gateway, así que el nuevo código debería estar activo).
