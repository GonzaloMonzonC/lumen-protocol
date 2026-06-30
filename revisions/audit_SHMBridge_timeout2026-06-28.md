# SHM read timeout: thinking/bridge

Fecha: 2026-06-28

## Síntoma
- `RuntimeError: [lumen-thinking-shm] SHM read timeout`

## Origen por código
`implementations/mcp-servers/plugins/lumen-shm-bridge/__init__.py: _read_shm()`

## Hallazgo paralelo (auditoría docs)
- README.md dice 108 tools.
- Suma expuesta en el mismo README: 13 filesystem + 2 web + 46 thinking + 5 objective loop + 40 PDB = 106.
- Correlación: hay al menos 2 unidades de discrepancia en la claim pública inicial del repo.
