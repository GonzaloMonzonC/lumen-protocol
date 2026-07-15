# lumen-pdb

Motor experimental de las siete operaciones núcleo de PDB sobre
[`redb`](https://www.redb.org/), expuesto a Python mediante una ABI C y
`ctypes`.

## Compatibilidad binaria de claves

`src/subkey.rs` es un puerto 1:1 de `pdb_tools.encode_subkey`. Los 31 casos de
`tests/golden_subkey.json` fueron generados por Python e incluyen cadenas
vacías, `None` legacy, negativos, `-0.0`, floats extremos, Unicode, cadenas
largas y claves multinivel. `cargo test` exige igualdad byte a byte.

Esto hace migrables las parejas raw `(subkey, value)` sin recodificar la clave.
Un `value=NULL` estructural de SQLite se representa mediante el sentinel raw
vacío en redb; los valores de usuario siempre son JSON y no colisionan con él.
No significa que un fichero físico SQLite pueda abrirse con redb ni al revés:
`pdb_migrate.py` realiza la conversión de contenedor.

## Operaciones y ABI

El crate implementa `SET`, `GET`, `$ORDER`, `$DATA`, `KILL`, `$INCREMENT` y
`MERGE`, además de bulk set, count y flush. `src/ffi.rs` exporta:

`lp_open`, `lp_close`, `lp_free`, `lp_set`, `lp_set_many`, `lp_get`,
`lp_order`, `lp_data`, `lp_kill`, `lp_incr`, `lp_merge`, `lp_count` y
`lp_flush`.

Los buffers devueltos por la ABI pertenecen al caller y deben liberarse con
`lp_free`. Python encapsula este contrato en `mcp-servers/pdb/lumen_pdb.py`.

## Compilar y validar

```bash
cd implementations/rust/lumen-pdb
cargo fmt --check
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release

cd ../../..
python3 implementations/python/pdb-sync/tests_redb.py
```

Estado verificado el 2026-07-15: Rust 4/4, storage Python/FFI 38/38 y suite
offline completa 494/494.

## Selección de motor

La selección se aplica a consumidores de la API núcleo `lumen_pdb.connect`:

```python
from lumen_pdb import connect

db = connect("state.redb", engine="redb")
db.set("STATE", ["agent", 1], {"status": "ready"})
print(db.get("STATE", ["agent", 1]))
db.close()
```

- `PDB_ENGINE=sqlite` es el valor por defecto.
- `PDB_ENGINE=redb` carga la dylib de release y usa `PDB_REDB_PATH` o una ruta
  derivada de `PDB_PATH`.
- `LUMEN_PDB_LIB` permite indicar una dylib concreta.
- Si redb se solicita pero la dylib no puede compilarse/cargarse, `connect`
  avisa por stderr y vuelve a SQLite.
- Un valor de engine desconocido se rechaza; no activa un fallback silencioso.

La capa redb cubre solo las siete operaciones núcleo. Historial, triggers,
particionado, SQL libre y el resto de extensiones continúan siendo SQLite-only.

## Migración one-shot

```bash
python3 implementations/mcp-servers/pdb/pdb_migrate.py \
  --src implementations/mcp-servers/pdb/lumen-pdb.db \
  --dst /tmp/lumen-pdb.redb \
  --verify
```

El destino debe ser nuevo. `--force` lo reemplaza de forma explícita. La
migración lee SQLite por chunks, usa una transacción redb por chunk, fuerza un
flush durable y, con `--verify`, compara todas las claves y todos los valores
byte a byte.

## Benchmark SQLite vs redb

Comando reproducible:

```bash
python3 implementations/python/pdb-sync/benchmark_redb.py \
  --iterations 3000 \
  --json implementations/rust/lumen-pdb/benchmark_redb_vs_sqlite.json
```

Resultado local (Apple Silicon, macOS 15.7.7, Python 3.14.6; SQLite
WAL/NORMAL, redb Eventual):

| Operación | SQLite ops/s | redb ops/s |
|---|---:|---:|
| bulk SET, una transacción | 1,486,099 | 570,654 |
| SET + commit por operación | 90,122 | 5,507 |
| GET existente | 321,377 | 328,498 |
| INCREMENT + commit por operación | 97,088 | 6,237 |

En esta carga monohilo, redb iguala ligeramente la lectura pero no mejora la
escritura; el coste de una transacción por SET/INCREMENT es mucho mayor. El
resultado no justifica cambiar el motor por rendimiento sin medir antes
concurrencia, batches y durabilidad sobre el hardware objetivo. Los datos raw
están en `benchmark_redb_vs_sqlite.json`.

## Durabilidad

redb usa `Eventual` por defecto, comparable al objetivo operativo de SQLite
`synchronous=NORMAL`. `LUMEN_PDB_DURABILITY=immediate` fuerza durabilidad por
commit. `lp_flush`/`flush()` crea un checkpoint `Immediate`, y el migrador lo
ejecuta antes de verificar y cerrar.
