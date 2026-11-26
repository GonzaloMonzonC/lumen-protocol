# DDP de hechos — índice

> Replicación de un registro append-only de hechos firmados entre nodos LUMEN.
> **Este es el DDP de los papers** (flota, criptomoneda, enjambre), no el de
> sincronización de claves de la PDB.
>
> Última actualización: 26-nov-2026.

---

## Por dónde empezar

| Si quieres… | Lee |
|---|---|
| **Saber qué funciona hoy** | [`ESTADO-REAL-POR-AFIRMACION.md`](ESTADO-REAL-POR-AFIRMACION.md) — sección *Replicación de hechos* |
| Entender por qué está diseñado así | [`DDP-ESCENARIOS-PAPERS.md`](DDP-ESCENARIOS-PAPERS.md) |
| Ver el protocolo | [`DDP-LUMEN-SPEC.md`](DDP-LUMEN-SPEC.md) |
| Configurar un nodo | [`DDP-CONFIGURABLE-PERFILES.md`](DDP-CONFIGURABLE-PERFILES.md) |
| Los números medidos | [`COSTE-VERIFICACION-NAS-VS-PC.md`](COSTE-VERIFICACION-NAS-VS-PC.md) |

---

## 1 · Diseño y decisiones

| Documento | Qué contiene |
|---|---|
| [`DDP-ESCENARIOS-PAPERS.md`](DDP-ESCENARIOS-PAPERS.md) | **La corrección de fondo**: no es sincronizar la PDB entre pares, es replicar **hechos**. Sin consenso en el núcleo |
| [`DDP-ESCENARIOS-estudio.md`](DDP-ESCENARIOS-estudio.md) | Estudio previo de escenarios E1–E4 y por qué el sync de PDB no bastaba |
| [`DDP-PROTOTIPOS-A-vs-B.md`](DDP-PROTOTIPOS-A-vs-B.md) | Hechos (A) frente a estado convergente (B). Veredicto: *"A donde hay que probar, B donde no"* |
| [`DDP-CONFIGURABLE-PERFILES.md`](DDP-CONFIGURABLE-PERFILES.md) | Todo configurable: 4 perfiles con políticas opuestas, y el banco que prueba que cada uno cumple en su escenario |
| [`DDP-SPLIT-BRAIN-DISENO.md`](DDP-SPLIT-BRAIN-DISENO.md) | Split-brain: por qué no se puede tratar igual una reinstalación y una partición |
| [`DDP-LUMEN-SPEC.md`](DDP-LUMEN-SPEC.md) | Cabecera de 6 bytes, cinco tipos, base-100, y **lo que no garantiza** |

## 2 · Construcción y verificación

| Documento | Qué contiene |
|---|---|
| [`DDP-BARCO-CODIGO-REAL.md`](DDP-BARCO-CODIGO-REAL.md) | Del prototipo a código: Ed25519 real, perfil desde fichero, cadena real |
| [`DDP-FLOTA-E2E.md`](DDP-FLOTA-E2E.md) | Verificación de flota: los 5 casos, incluido el barco que firma a nombre de otro |
| [`FLOTA-EN-RECEPCION.md`](FLOTA-EN-RECEPCION.md) | El certificado viaja por el cable; el hub ya no acepta a cualquiera con una clave |
| [`DDP-EPOCH-CUSTODIA.md`](DDP-EPOCH-CUSTODIA.md) | Un salto de epoch exige la firma del anterior. Sin esto, cualquiera sube el epoch |
| [`DDP-QUIC-E2E.md`](DDP-QUIC-E2E.md) | 200 mensajes por un socket TLS 1.3 de verdad |
| [`QUIC-SERVIDOR-PARALELO.md`](QUIC-SERVIDOR-PARALELO.md) | Aceptación paralela: de 10 a 40 barcos |
| [`POLL-SIN-AMBIGUEDAD.md`](POLL-SIN-AMBIGUEDAD.md) | `Vacio` frente a `Cerrado`: cierra la ambigüedad del `0` |
| [`PUMP-ESTADO.md`](PUMP-ESTADO.md) | Lo mismo en el ciclo completo |

## 3 · Almacenamiento y durabilidad

| Documento | Qué contiene |
|---|---|
| [`DDP-DURABILIDAD-CONFIGURABLE.md`](DDP-DURABILIDAD-CONFIGURABLE.md) | `sync` / `nosync` / `lote` en el perfil. Decide el **disco**, no la máquina |
| [`DDP-DURABILIDAD-MEDIDA-NAS.md`](DDP-DURABILIDAD-MEDIDA-NAS.md) | Primera medida en la NAS |
| [`DDP-SYNC-VS-NOSYNC-NAS-PC.md`](DDP-SYNC-VS-NOSYNC-NAS-PC.md) | **NAS frente a PC**: en NVMe el fsync no cuesta nada; en HDD cuesta 291× |
| [`MAPSIZE-POR-AMBITO.md`](MAPSIZE-POR-AMBITO.md) | 1 GB aguanta 24 días de barcos y **4 horas** de un ledger con 1 M de usuarios |
| [`MAPSIZE-EN-EL-PERFIL.md`](MAPSIZE-EN-EL-PERFIL.md) | Una sola fuente de verdad, y el techo de 1.400 MB en 32 bits |
| [`MAP-FULL-DIAGNOSTICO.md`](MAP-FULL-DIAGNOSTICO.md) | **El diagnóstico que costó horas**: no era control de flujo, era `MDB_MAP_FULL` escondido en un error genérico |
| [`RAM-HUB-MEDIDA.md`](RAM-HUB-MEDIDA.md) | La RAM del hub es el caché de LMDB, no una fuga |

## 4 · Medición

| Documento | Qué contiene |
|---|---|
| [`COSTE-VERIFICACION-MEDIDO.md`](COSTE-VERIFICACION-MEDIDO.md) | En el PC: **lo caro es la cadena de hashes, no las firmas** |
| [`COSTE-VERIFICACION-NAS-VS-PC.md`](COSTE-VERIFICACION-NAS-VS-PC.md) | **En ARM la conclusión se invierte**: las firmas cuestan 45× más |
| [`VERIFICACION-POR-LOTES-NAS.md`](VERIFICACION-POR-LOTES-NAS.md) | Trocear no salva la firma individual; los sellos sí |
| [`ED25519-EN-ARM-DIAGNOSTICO.md`](ED25519-EN-ARM-DIAGNOSTICO.md) | Por qué es 45× más lento: **arquitectura, no frecuencia** (sin NEON) |
| [`FLOTA-REPLICANDO.md`](FLOTA-REPLICANDO.md) | Primer escenario completo: barcos que escriben y convergen en un hub |
| [`SIMULACION-FLOTA-20-NODOS.md`](SIMULACION-FLOTA-20-NODOS.md) | 20 procesos reales escribiendo a la vez |
| [`NAS-NODO-PRUEBAS.md`](NAS-NODO-PRUEBAS.md) | El nodo de pruebas aislado en la NAS |
| [`NAS-LOTE-Y-QUIC-MEDIDO.md`](NAS-LOTE-Y-QUIC-MEDIDO.md) | Lote y QUIC en ARMv7. **47 s para 21.600 muestras** |

---

## Lo que NO está

Para que nadie lo busque en vano:

| | |
|---|---|
| **Consenso** (PoW/PoS/BFT) | **No existe, por diseño.** El paper no lo pide |
| **Revocación de certificados** | No existe |
| **Caducidad de certificados** | No existe |
| **Epoch de recuperación** con clave perdida | Diseñado, no construido |
| **Réplica parcial** a escala (enjambres de miles) | La política existe en el perfil, sin probar |
| **BLE / LoRa / Wi-Fi Direct** | El trait `Transport` lo permitiría; **cero líneas escritas** |
| **DHT** | El descubrimiento es multicast en LAN, y el ADR explica por qué |

## Los tres números que resumen el estado

| | |
|---|---|
| **480.000** hechos de 40 barcos, cero pérdidas | flota replicando |
| **4,1 s** para 21.600 muestras (6 h de barco) | en NAS ARMv7 con `nosync` |
| **45×** más lento verificar en ARM que en x86 | por qué la firma por bloque no es opcional |
