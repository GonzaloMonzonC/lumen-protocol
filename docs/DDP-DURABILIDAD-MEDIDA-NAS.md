# Durabilidad unificada — medida real en la NAS

> 2026-11-24. Unificado el mecanismo (una sola fuente de verdad) y **medido en
> la NAS ARMv7** con el binario nuevo.

---

## 1 · La unificación

Antes había **dos mecanismos para lo mismo**:

| Mecanismo | Dónde | Problema |
|---|---|---|
| `LUMEN_LMDB_NOSYNC` | variable de entorno | fuera del perfil |
| `durabilidad` | campo del perfil | el camino nuevo |

Si alguien configurase el perfil en `sync` y tuviera la variable puesta, el
store iría sin fsync **sin que nadie lo supiera**. Dos verdades para lo mismo.

### Solución

- `LmdbStore::open_con_durabilidad(dir, nosync)` — el parámetro manda.
- `MemoryHost::from_lmdb_con_durabilidad(dir, nosync)` — el camino nuevo.
- `PerfilReplicacion::store_sin_fsync()` — **única** derivación: solo `nosync`
  desactiva el fsync; `sync` y `lote` lo conservan (el lote lo agrupa el
  escritor, no el store).
- La variable de entorno se sigue aceptando **solo** en `open()` y en
  `mvm-nas`, por compatibilidad, y **no puede contradecir** a quien pasa el
  parámetro explícito.

Hay test: `el_store_respeta_la_durabilidad_explicita_y_no_el_entorno`.

## 2 · Medición REAL en la NAS (ARMv7, 242 MB RAM)

Binario `mvm-nas-test` con `LUMEN_DURABILIDAD`, en `/volume1/backup/lumen-test/`.

| Escrituras | `sync` | `nosync` | Factor |
|---|---:|---:|---:|
| 100 | 4.819 ms | **16,4 ms** | **294×** |
| 1.000 | 63.359 ms | 192 ms | 330× |
| **21.600** (6 h de barco a 1 Hz) | ~23 min (extrapolado) | **4.120 ms** | **~336×** |

**El dato que cierra el diseño: un barco con 6 horas de corte sincroniza su
bitácora en 4,1 segundos.** Con fsync por muestra serían 23 minutos.

Y confirmado que la unificación funciona: el binario reporta
`durabilidad=nosync` / `durabilidad=sync` y obedece.

## 3 · Qué significa para cada perfil

| Perfil | Durabilidad | 21.600 muestras |
|---|---|---:|
| barco | `lote` 64 | ~4,1 s (el lote agrupa; el fsync cae 1 de cada 64) |
| enjambre | `nosync` | ~4,1 s |
| ledger | `sync` | ~23 min ← **aquí sí se paga, y es correcto** |
| config | `nosync` | instantáneo |

El `sync` del ledger parece caro, pero es **la decisión correcta**: un registro
contable no puede perder escrituras. Y un ledger no escribe 21.600 muestras de
telemetría: escribe transacciones, muchas menos.

## 4 · Verificado

```
escritura::tests::el_perfil_decide_si_el_store_va_sin_fsync          OK
escritura::tests::el_store_respeta_la_durabilidad_explicita_y_no_el_entorno  OK
escritura::tests::los_cuatro_perfiles_traen_su_durabilidad           OK
```

**183 tests, todos verdes.**

## 5 · Lo que sigue pendiente y lo digo claro

1. **El `lote` no está medido como tal.** Lo medido son los extremos (`sync` y
   `nosync`). El lote agrupa commits, y para ejercitarlo desde M haría falta
   exponerlo en el intérprete. El dato de `nosync` en 4,1 s es una **cota
   superior optimista**; el lote real estará entre 4,1 s y 23 min, y más cerca
   del primero porque el fsync cae 1 de cada 64.
2. **La replicación sigue sin estar en la NAS.** `mvm-nas` no usa
   `lumen-nodo`: lo probado en la NAS es el **motor y LMDB**, no el envío por
   QUIC ni la verificación de flota.
3. **El nodo de pruebas escribe en `/volume1/backup/lumen-test/`**, separado de
   neferu. Verificado que el `mvm-nas` de producción sigue con su binario del
   7-oct.
