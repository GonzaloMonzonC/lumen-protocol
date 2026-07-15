#!/usr/bin/env python3
"""Conformance entrypoint for the Fase 6 Tokio MVM integration test."""

import importlib.util
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST = ROOT / "mcp-servers" / "pdb" / "tests" / "test_mvm_rust.py"

passed = 0
try:
    spec = importlib.util.spec_from_file_location("test_mvm_rust", TEST)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as directory:
        module.test_tokio_mvm_live_storage_mailbox_timer_and_restore(Path(directory))
    passed = 1
    print("  ✅ Tokio jobs + live SQLite + mailbox + timer + restore + cron")
except Exception as error:
    print(f"  ❌ Tokio MVM integration: {error}")

print(f"\n{passed}/1 tests passed")
raise SystemExit(0 if passed else 1)
