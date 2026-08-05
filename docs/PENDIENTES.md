# PENDIENTES — Ecosistema Cadences Lab

## P1. Duplicación de instancias de poli_server por sesión (ALTA)

**Problema detectado**: 2026-08-05 — hay 4 procesos `poli_server.py` corriendo a la vez
(Python313, venv, uv). Cada sesión nueva del gateway parece lanzar una instancia nueva
del MCP server de Poli en vez de conectarse a la existente.

**Impacto**: memoria desperdiciada, estado fragmentado entre instancias, respuestas
cacheadas de sesiones viejas (vimos una respuesta de otra sesión en un test).

**Investigación pendiente**:
- ¿Cómo lanza el MCP manager de Hermes los servers stdio? ¿Por sesión o por proceso?
- ¿`poli_server.py` debería correr como daemon único con transporte lumen/SHM en vez
  de stdio por sesión?
- Ver si hay config para compartir instancia (`mcp_servers` → reuse / singleton)
- Ver el watchdog de Poli (¿existe? ¿relanza instancias?): `watchdog_fabella.py` solo
  cubre el bridge MTProto

**Solución deseada**: 1 instancia de Poli. Cuando llega una sesión nueva, hablar con el
Poli activo (mismo proceso), no crear uno nuevo.

**Referencia**: `config.yaml` → `mcp_servers.poli` ; `poli_server.py` → `_STATE`

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
