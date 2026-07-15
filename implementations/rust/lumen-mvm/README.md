# lumen-mvm

Scheduler de Jobs M de la Fase 6. Cada Job vive en una task Tokio y recibe
comandos/mensajes por `tokio::sync::mpsc`; M-Light Rust ejecuta un slice de gas
por turno. `tokio::time` despierta `HIBERNATE` y dispara cron sin polling.

SQLite sigue siendo la fuente de verdad. La C ABI (`lmvm_new`,
`lmvm_call_json`, `lmvm_free`, `lmvm_string_free`) recibe un callback JSON que
el wrapper `lumen_mvm.py` conecta con `pdb_tools`. Las operaciones sobre
globals son live —no hay snapshot/diff— y los cambios conservan mapping,
triggers, índices, CDC y journal. Cada transición persiste un snapshot completo
en `^STATE(pid,"rust_snapshot")` y los campos legacy en una sola transacción.

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release
python3 benchmark.py
```

Activación progresiva:

```bash
MVM_ENGINE=rust python3 implementations/python/pdb-sync/run_conformance.py mvm
```

Si la dylib no está disponible, `mvm.py` conserva el scheduler Python. Los
procesos Rust se restauran automáticamente desde `^STATE`; los timers
`^SCHEDULE` recuperan el tiempo restante y los cron M desde `^CRON` vuelven a
registrarse en Tokio.

Una transacción M es atómica dentro de un fichero SQLite. El Host live sí
resuelve `MAP_CFG`/`PART_CFG` operación a operación, pero un `TSTART` no puede
abarcar varios ficheros; ese caso falla en vez de prometer atomicidad parcial.
