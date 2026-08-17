#!/usr/bin/env bash
# =============================================================================
# LUMEN → Hermes Agent MCP setup
#
# Registra los 4 MCP servers de lumen-protocol (filesystem, web, thinking, pdb)
# en Hermes Agent via JSON-RPC stdio (la ruta verificada con el cliente MCP
# de Hermes). Crea el venv e instala lumen-mcp si hace falta.
#
# Uso:   bash scripts/setup_hermes_mcp.sh
#        (tambien funciona en git-bash/MSYS sobre Windows)
# =============================================================================
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python}"

echo "◆ LUMEN → Hermes MCP setup"
echo "  repo: $REPO"

# ── 1) venv ─────────────────────────────────────────────────────────────────
if [ ! -x "$REPO/.venv/Scripts/python.exe" ] && [ ! -x "$REPO/.venv/bin/python" ]; then
  echo "◆ Creando venv..."
  "$PYTHON" -m venv "$REPO/.venv"
fi
if [ -x "$REPO/.venv/Scripts/python.exe" ]; then
  VENV_PY="$REPO/.venv/Scripts/python.exe"
else
  VENV_PY="$REPO/.venv/bin/python"
fi
echo "  venv python: $VENV_PY"

# ── 2) lumen-mcp (editable) ─────────────────────────────────────────────────
if ! "$VENV_PY" -c "import lumen" >/dev/null 2>&1; then
  echo "◆ Instalando lumen-mcp (editable)…"
  "$VENV_PY" -m pip install -e "$REPO/implementations/python"
fi

# ── 3) hermes CLI ───────────────────────────────────────────────────────────
if ! command -v hermes >/dev/null 2>&1; then
  echo "✗ 'hermes' no está en el PATH. Instala Hermes Agent primero:" >&2
  echo "  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash" >&2
  exit 1
fi

# ── 4) registrar los 4 servers (idempotente) ────────────────────────────────
for name in filesystem web thinking pdb; do
  if hermes mcp list 2>/dev/null | grep -q "lumen-$name"; then
    echo "✓ lumen-$name ya registrado"
  else
    echo "◆ Registrando lumen-$name…"
    hermes mcp add "lumen-$name" \
      --command "$VENV_PY" \
      --args "$REPO/implementations/mcp-servers/$name/server.py"
  fi
done

# ── 5) verificación ─────────────────────────────────────────────────────────
echo
echo "◆ Verificación:"
hermes mcp list
echo
echo "✓ Listo. Reinicia Hermes (/reset o sesión nueva) para cargar las"
echo "  115 tools (búscalas como mcp__lumen_*)."
