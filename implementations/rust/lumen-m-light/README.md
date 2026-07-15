# lumen-m-light

Compilador y stack-VM Rust de M-Light (Spec M-Agent v0.2). Produce bytecode
JSON versionado y un estado reanudable apto para persistir en `^STATE`.

```bash
cargo test
cargo clippy --all-targets -- -D warnings
cargo build --release
python3 benchmark.py
```

La ABI exporta `lm_compile_json`, `lm_execute_json` y `lm_string_free`. El
wrapper Python está en `implementations/mcp-servers/pdb/lumen_mlight.py`:

```python
from lumen_mlight import execute, execute_sqlite

pure = execute('S x=2+3*4 W x')
persisted = execute_sqlite('S ^RESULT("x")=2+3*4')
```

En el servidor PDB, `MLIGHT_ENGINE=rust` habilita el motor nuevo;
`MLIGHT_ENGINE_STRICT=1` desactiva el fallback a Python. SQLite continúa
siendo la persistencia canónica. El VM Rust no abre la BD: el wrapper carga un
snapshot y aplica el diff por `pdb_tools` en una transacción SQLite única,
conservando triggers, índices y journal.

Una referencia indirecta construida completamente en runtime no permite saber
qué namespace precargar. En ese caso el adaptador exige
`execute_sqlite(source, namespaces=["NS1", "NS2"])`; falla explícitamente en
vez de devolver una lectura vacía silenciosa.

El snapshot cubre el fichero SQLite canónico. Namespaces redirigidos por
`MAP_CFG` o `PART_CFG` se rechazan hasta que el Host live pueda coordinar más
de una conexión en Fase 6.

El estado incluye IP, variables, pila, call stack, scopes `NEW`, frames de
`FOR`, output, errores y contadores de gas. Las transacciones son secciones no
yielding y hacen rollback automático en error. El commit del diff es atómico y
comprueba que las claves tocadas no cambiaron desde el snapshot; si cambiaron,
devuelve `PDB_CONFLICT` en lugar de sobrescribir. El Host live se conectará al
scheduler Tokio en Fase 6.
