# Durabilidad configurable — sync / nosync / lote

> 2026-11-24. El modo de confirmar en disco sale del perfil, no del código.
> Código: `src/escritura.rs` · datos de la NAS en `NAS-NODO-PRUEBAS.md`.

---

## 1 · Por qué es del perfil y no una constante

Lo que decide no es la máquina: **es el disco**.

| Dónde | Disco | fsync cuesta | Conviene |
|---|---|---|---|
| NAS Synology ARMv7 | mecánico/lento | **71 ms** | `nosync` o `lote` |
| Portátil | NVMe | microsegundos | `sync` da igual |
| Dron | efímero | — | `nosync` (la memoria se va con la batería) |
| Servidor contable | SSD | barato | `sync` (no se puede perder nada) |

Por eso es una línea del perfil y no una decisión del motor.

## 2 · Los tres modos

| Modo | Qué hace | Se pierde ante un corte | Medido en NAS |
|---|---|---|---:|
| `sync` | `commit` + `fsync` por escritura | nada | **71 ms/escritura** |
| `nosync` | sin `fsync` | lo último en vuelo | **0,41 ms/escritura** |
| `lote` | un `commit` cada N | como mucho el lote en curso | intermedio |

Medido en la NAS: **173× de diferencia** entre `sync` y `nosync`.

## 3 · Qué lleva cada perfil por defecto

| Perfil | Durabilidad | Por qué |
|---|---|---|
| **barco** | `lote` (64) | Disco lento a bordo. Con `sync` serían 71 ms por muestra de 1 Hz; por lote baja a ~1 ms y se pierde como mucho el último segundo |
| **enjambre** | `nosync` | Un dron pierde la memoria al aterrizar igual. Pagar 70 ms para un dato que se va con la batería no tiene sentido |
| **ledger** | `sync` | Un registro contable no puede perder escrituras. Aquí sí se paga el fsync |
| **config** | `nosync` | Si se pierde una temperatura de agente, se vuelve a escribir |

## 4 · El cálculo que esto resuelve

Replicar las 21.600 muestras de un barco (6 h a 1 Hz):

| Modo | Tiempo |
|---|---:|
| `sync` | **26 minutos** ❌ |
| `lote` 64 | **≈ 5 segundos** ✅ |
| `nosync` | 4,5 segundos |

## 5 · Cómo se implementa

`src/escritura.rs` — un `Escritor` que agrupa antes de confirmar:

```rust
let mut w = Escritor::nuevo(&mut host, &perfil)?;   // lee el perfil
for h in &hechos { w.escribir(h)?; }                 // agrupa según el modo
w.terminar()?;                                       // cierra el lote
```

Usa `Host::transaction_start/commit`, **que ya existía en el trait**: no hubo
que tocar el motor. Y tiene `Drop` como red de seguridad: si alguien olvida
`terminar()`, el lote se cierra igual.

## 6 · Verificado

```
escritura::tests::el_perfil_de_barco_agrupa_en_lotes       -> 100 hechos / lote 10 = 10 commits
escritura::tests::sync_hace_un_commit_por_hecho            -> 20 hechos = 20 commits
escritura::tests::el_lote_con_resto_no_pierde_los_ultimos  -> 105 hechos / lote 10 = 11 commits, 105 guardados
escritura::tests::nosync_escribe_todos_los_hechos
escritura::tests::un_perfil_invalido_no_crea_escritor
escritura::tests::los_cuatro_perfiles_traen_su_durabilidad
```

**El caso del resto es el importante**: 105 hechos con lote 10 son 10 lotes
completos y 5 sueltos. Sin cerrar el último lote, esos 5 se perderían en
silencio. Hay test.

**181 tests, todos verdes.**

## 7 · Lo que queda

- **Medir el `lote` en la NAS con el binario nuevo.** Los 71 ms y 0,41 ms están
  medidos; el punto medio del lote está calculado, no medido.
- **`LUMEN_LMDB_NOSYNC` es variable de entorno**, no campo del perfil. Debería
  unificarse: hoy hay dos mecanismos para lo mismo.
- **La replicación sigue sin estar en el binario de la NAS** (`mvm-nas` no usa
  `lumen-nodo`).
