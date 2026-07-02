#!/usr/bin/env python3
"""PDB CLI — command-line entry point.

Usage:
    pdb shell            — Interactive shell (MUMPS commands)
    pdb shell -c "CMD"   — One-shot command
    pdb shell --json     — JSON output mode
    pdb server           — Start JSON-RPC server
    pdb help             — Show help
"""

import sys
import os
from pathlib import Path

_PDB_DIR = Path(__file__).resolve().parent


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("help", "-h", "--help"):
        print(__doc__)
        return

    subcommand = sys.argv[1]

    if subcommand == "shell":
        sys.argv.pop(1)  # remove 'shell'
        shell_path = _PDB_DIR / "pdb_shell.py"
        import subprocess
        result = subprocess.run([sys.executable, str(shell_path)] + sys.argv[1:])
        sys.exit(result.returncode)

    elif subcommand == "server":
        server_path = _PDB_DIR / "server.py"
        import subprocess
        result = subprocess.run([sys.executable, str(server_path)])
        sys.exit(result.returncode)

    else:
        print(f"Unknown subcommand: {subcommand}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
