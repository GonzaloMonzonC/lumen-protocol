# PROCEDIMIENTO — conectar el Asus como nodo a cadences.app

**Fecha:** 2026-10-19 · **Estado:** PC verificado (200 OK), Asus pendiente

---

## Lo que ya está hecho (en el PC)

| Pieza | Estado |
|---|---|
| Endpoint `/api/nodes/sync` | ✅ desplegado en `cadences.app` |
| Secreto `NODES_HMAC_KEY` | ✅ instalado en Cloudflare (clave cuántica Tuna-17, job 1233912) |
| Cliente `tools/node_link.py` | ✅ en `lumen-protocol` |
| Auth verificada | ✅ clave buena → 200 · clave mala → **401** |

**La clave es cuántica de verdad**: 64 hex (256 bits) generados en `Tuna-17`, job `1233912`, del 2026-08-03. Id 1 de las 25 disponibles, ninguna usada antes.

---

## Paso 1 — En el Asus: traer el código

```bash
cd ~/lumen-protocol          # o donde lo tengas
git pull origin main
```

**Qué esperar:** deberías ver los commits nuevos, incluido `47bf9682` (sesión de equipo) y los ficheros `tools/node_link.py`.

Verifica:

```bash
ls -la tools/node_link.py
git log --oneline -3
```

---

## Paso 2 — Pasar la clave (por fichero, sí)

**No** la copies al repo. Va a tu home, con permisos restringidos.

### Opción A — desde el PC (recomendado si tienes SSH al Asus)

En el **PC**:

```bash
scp ~/.cadences-node.key gonzalo@<IP-DEL-ASUS>:~/.cadences-node.key
```

Luego, en el **Asus**:

```bash
chmod 600 ~/.cadences-node.key
```

### Opción B — a mano

En el **PC**, muestra la clave una vez:

```bash
cat ~/.cadences-node.key
```

En el **Asus**:

```bash
nano ~/.cadences-node.key     # pega la clave, una sola línea, sin espacios
chmod 600 ~/.cadences-node.key
```

### Opción C — sin fichero (variable de entorno, solo para una sesión)

```bash
export CADENCES_NODE_KEY="<la-clave>"
```

**Recomiendo A o B.** La C se pierde al cerrar la terminal.

### Comprobación de que el fichero está bien

```bash
wc -c ~/.cadences-node.key     # debe dar 65 (64 hex + salto de línea)
```

Si da 65, está bien. Si da más, tiene espacios o varias líneas.

---

## Paso 3 — Probar desde el Asus

```bash
cd ~/lumen-protocol
python tools/node_link.py ping
```

**Qué esperar:**

```
OK   status=200 :: True
```

Si sale eso, **el Asus ya se autentica contra cadences.app**.

### Si sale error

| Error | Causa | Arreglo |
|---|---|---|
| `No hay clave.` | no encuentra el fichero | comprobar `~/.cadences-node.key` existe |
| `FALLO status=401 :: Firma inválida.` | clave distinta a la del servidor | recopiar la clave del PC |
| `FALLO status=401 :: Timestamp fuera de ventana.` | reloj del Asus desfasado > 5 min | `sudo ntpdate -s pool.ntp.org` |
| `FALLO status=503` | falta `NODES_HMAC_KEY` en Cloudflare | volver a instalarla |
| `FALLO status=405` | endpoint no desplegado | `npm run deploy` en ProjectOS |
| `URLError` / timeout | sin red o DNS | comprobar `ping cadences.app` |

---

## Paso 4 — Registrar el nodo

```bash
python tools/node_link.py register --node hermes-asus
```

**Qué esperar:**

```
OK   status=200 :: identidad verificada; persistencia de nodos pendiente
     nodo registrado: hermes-asus
```

**Nota honesta:** hoy `register` solo **confirma la identidad**. La tabla `nodes` en D1 (para que el nodo "exista" en cadences.app con su manifiesto y last-seen) es el **siguiente paso**. Ahora mismo el valor de esto es: **la autenticación funciona entre máquinas.**

---

## Paso 5 — Probar el turno compartido (esto ya lleva PDB, no HMAC)

**Ojo, esto es importante y hay que ser claro:**

`team_*` y `contract_*` funcionan sobre **la PDB local del nodo**. Para que el Asus vea los turnos del PC, hay **dos caminos**:

| Camino | Qué requiere | Estado |
|---|---|---|
| **A — PDB compartida** | que ambos apunten al mismo `.db` (NAS, carpeta compartida) | no montado |
| **B — sincronizar por HTTPS** | `pull`/`push` de turnos vía `/api/nodes/sync` | **endpoint solo tiene `ping`/`register`** |

**Es decir: el HMAC ya funciona, pero el intercambio de turnos entre máquinas todavía no.** Eso es lo siguiente que hay que construir (`pull`/`push` con fusión por id, nunca overwrite).

**Lo que sí puedes hacer hoy en el Asus:** usar `team_*` localmente (abrir turnos, reclamar, handoff) — el mecanismo funciona, solo que sobre su propia PDB.

---

## Resumen de lo que hay que hacer en el Asus

```bash
# 1. traer código
git pull origin main

# 2. clave (desde el PC: scp ~/.cadences-node.key ...)
chmod 600 ~/.cadences-node.key

# 3. probar
python tools/node_link.py ping

# 4. registrar
python tools/node_link.py register --node hermes-asus
```

**4 comandos.** Si el paso 3 da `OK status=200`, el enlace está hecho.

---

## Sobre la seguridad (lo que planteaste)

Tu razonamiento era correcto: **es como una API key**. Pero con matices que apliqué:

| Tu idea | Lo que hice |
|---|---|
| "Usar la HMAC actual" | **No**: creé una nueva. La actual está commiteada en `ProjectOS` (`FALLBACK_HMAC_KEY` en `systemone.js`) — aunque el repo sea privado, una clave en el historial git es difícil de revocar |
| "Guardarla en cadences.app" | ✅ En Cloudflare como **secret** (nunca en el repo, nunca en el bundle) |
| "Como una API key" | ✅ Exacto: HMAC con timestamp + ventana de 5 min + comparación en tiempo constante |
| "No es crítico" | ✅ De acuerdo: el riesgo real era **gastar tus créditos de Workers AI**, no acceder a datos |

### Dos cosas pendientes de seguridad

1. **Rotar `FALLBACK_HMAC_KEY`** en `systemone.js`. Aunque el repo sea privado, esa clave está en el historial.
2. **`NODES_HMAC_KEY` es de 256 bits cuánticos** — no hay prisa por rotarla (no es fuerza bruta viable).

**Lo que esta clave NO hace:** no da acceso a tu cuenta, ni a D1, ni a la consola de Cloudflare. Solo permite llamar a `/api/nodes/sync`. Por eso tu valoración de riesgo era razonable.
