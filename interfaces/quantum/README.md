# QBI — Quantum Backend Interface (interfaz cuántica del MVM)

> **Estado**: v0.1 (2026-09-04) · **Repo**: lumen-protocol (MIT) — *solo la interfaz*.
> Implementación funcional de referencia (privada): `lumen-mcp-quantum` (Quantum
> Inspire: QPU Tuna-17, emulador QX) — NO es parte de este repo MIT.

QBI define el contrato entre **el ecosistema Lumen** (agentes M, workers, Hermes)
y **cualquier backend cuántico**. Cualquiera puede implementar QBI sobre su propio
backend (IBM, AWS Braket, emulador local, ...) y los consumidores funcionan sin
cambios: el MVM llama a la interfaz, no al hardware.

## Principios

1. **Circuito = cQASM v3** (texto): `version 3.0`, `qubit[n] q`, `bit[n] b`,
   `b[i] = measure q[i]`. El dialecto real de cada backend puede restringir el
   set de gates; la interfaz NO inventa gates.
2. **Resultado = histograma** `{bitstring: count}` (counts). Es el único shape
   de resultado del contrato.
3. **Procedencia**: toda ejecución devuelve `job_id` y los resultados llevan
   `backend_id`/`backend_name`; un consumidor puede etiquetar `real` vs `emulador`.
4. **Dos modos de respuesta** (mismo endpoint):
   - JSON (default) → consumidores ricos (Hermes, workers, Python).
   - `?m=1` (o `Accept: text/plain`) → **modo M**: líneas planas separadas por
     `\n`, sin JSON (el `$DEVICE` del MVM no parsea JSON). Primera línea: `ok`
     o `error:<motivo>`.
5. **Caché**: los resultados completados se registran en el store compartido
   (PDB, namespace `^QUANTUM`) con `tipo` y `job_id` — la caché es del
   ecosistema, no del backend. Un consumidor M puede leer `^QUANTUM(...)`
   directamente si comparte store, o vía `/result/<job_id>`.
6. **Local por defecto**: el puente escucha en `127.0.0.1` (nunca `0.0.0.0`).
   Exposiciones remotas requieren auth explícita (p.ej. HMAC) fuera del contrato.

## Endpoints

| Método | Ruta | Body/Query | Respuesta (JSON) |
|---|---|---|---|
| GET | `/health` | — | `{ok: true}` |
| GET | `/backends` | — | `{ok, backends: [{id, name, status, is_hardware}]}` — `status ∈ idle\|executing\|completing\|offline\|error` |
| POST | `/run` | `{cqasm, backend_id, shots?, name?}` | `{ok, job_id, backend_id}` — sube y encola (no espera) |
| GET | `/result/<job_id>` | `?wait=30&m=1` | `{ok, status, counts?, backend_id?, job_id}` — espera hasta `wait` s si está en cola; al completar persiste en PDB `^QUANTUM` (`tipo: "qbi:<job_id>"`) |
| GET | `/random` | `?m=1` | `{ok, source, hex, backend}` — bytes aleatorios **cuánticos** (preferencia: QPU real online → librería de resultados reales cacheados → emulador). `source` SIEMPRE declara el origen real |
| GET | `/demo/<circuito>` | `?wait=40&m=1` | Conveniencia de prueba: ejecuta un circuito canónico y devuelve counts |

### Modo M (`?m=1`)

```
GET /backends?m=1        → ok
                          1|QX emulator|idle|false
                          7|Tuna-17|executing|true
GET /result/1418535?m=1  → ok
                          complete
                          {'00': 504, '01': 18, '10': 20, '11': 482}
GET /random?m=1          → ok
                          QPU real backend-7 (job 1418535)
                          3f9a2c1b8e4d07aa
```

Desde M (MVM con `$DEVICE` HTTP nativo; VERIFICADO 2026-09-04 con poli MVM):

```m
S ^R=$DEVICE("http:get","http://127.0.0.1:8090/backends?m=1")
W ^R
; → {"body":"ok\n1|QX emulator|idle|false\n...","ok":true,"status":200}
; El $DEVICE envuelve SIEMPRE en JSON {"body","ok","status"} — extrae el body así:
S B=$P($P(^R,"""body"":""",2),"""",1)   ; B = "ok\n1|QX emulator|..."
S LINEA1=$P(B,$C(10),1)
```

**Nota de arquitectura (verificado 2026-09-04)**: el store de globales del MVM
NO es el mismo que el PDB `^QUANTUM` de `qpdb.py` (leer `^QUANTUM(...)` desde M
devuelve vacío). La caché compartida se accede POR LA INTERFAZ (`/random`,
`/result/<job>`), nunca por lectura directa de globales del otro store.

## Circuitos canónicos (para `/demo` y pruebas)

| Nombre | Qubits | Gates | Uso |
|---|---|---|---|
| `bell` | 2 | H, CNOT | entrelazado básico, conectividad |
| `ghz3` / `ghz5` | 3/5 | H, CNOT | entrelazado multipartito |
| `cluster2x3` | 6 | H, CZ | estado de grafo 2D (MBQC) |
| `clusters0` | 6 | H, CZ, H(q0) | verificación de estabilizador (proxy ruido) |

## Implementar QBI (backend propio)

1. Sirve los endpoints con tu runner (sube tu circuito, devuelve counts).
2. Devuelve `backend_id`/`backend_name` y `status` reales.
3. Persiste completados en tu store `^QUANTUM` si quieres caché compartida.
4. Documenta tu dialecto de gates si no es H/CNOT/CZ/X.

La spec NO exige un proveedor concreto: un emulador local de 2 qubits que
implemente estos 6 endpoints ES un backend QBI.
