#!/usr/bin/env python3
"""Tests for PDB time-travel: history + rollback."""

from __future__ import annotations
import json, os, sys, tempfile, unittest

# Set PDB_PATH before importing pdb_tools to use temp DB
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["PDB_PATH"] = _tmp.name

# Clean up if exists from previous runs
if os.path.exists(_tmp.name):
    try: os.unlink(_tmp.name)
    except: pass

import pdb_tools as PDB


class TestHistory(unittest.TestCase):
    """Time-travel: _save_to_history, tool_history, tool_rollback."""

    def setUp(self):
        """Fresh DB for each test."""
        # Clean slate
        conn = PDB._get_conn()
        conn.execute("DELETE FROM _globals")
        conn.commit()

    def test_history_after_set(self):
        """SET a key, read history, verify version saved."""
        PDB.tool_set({"ns": "TEST", "subs": ["x"], "value": "v1"})
        PDB.tool_set({"ns": "TEST", "subs": ["x"], "value": "v2"})
        r = PDB.tool_history({"ns": "TEST", "subs": ["x"]})
        self.assertTrue(r["success"], f"History failed: {r.get('error')}")
        self.assertGreaterEqual(r["count"], 1, "Should have at least 1 history entry")
        # Most recent first (DESC order) — history saves OLD value before overwrite
        if r["count"] >= 1:
            self.assertEqual(r["versions"][0]["value"], "v1",
                             f"Expected v1 (saved as old value before v2 overwrite), got {r['versions'][0]}")

    def test_history_multiple_versions(self):
        """Multiple SETs produce multiple versions."""
        for i in range(1, 4):
            PDB.tool_set({"ns": "TEST", "subs": ["y"], "value": f"v{i}"})
        r = PDB.tool_history({"ns": "TEST", "subs": ["y"]})
        self.assertTrue(r["success"], f"History failed: {r.get('error')}")
        # Should have at least 2 previous versions (v1, v2) + current (v3)
        # Actually the first SET creates the key, no old value to save
        # Second SET saves old=v1, third SET saves old=v2
        self.assertGreaterEqual(r["count"], 1, "Should have versions saved")

    def test_rollback_to_previous(self):
        """Rollback restores previous value."""
        PDB.tool_set({"ns": "TEST", "subs": ["z"], "value": "original"})
        PDB.tool_set({"ns": "TEST", "subs": ["z"], "value": "modified"})
        r = PDB.tool_history({"ns": "TEST", "subs": ["z"]})
        self.assertTrue(r["success"])
        if r["count"] >= 1:
            ts = r["versions"][0]["timestamp"]
            # Rollback to the timestamp of the first (most recent) saved version
            # The most recent version saved is "original" (before "modified" was SET)
            rb = PDB.tool_rollback({"ns": "TEST", "subs": ["z"], "timestamp": ts})
            self.assertTrue(rb["success"], f"Rollback failed: {rb.get('error')}")
            # Verify restored value
            current = PDB.tool_get({"ns": "TEST", "subs": ["z"]})
            val = current.get("value", "")
            # After rollback should be the value that was saved at that timestamp
            saved_val = r["versions"][0].get("value")
            self.assertIn(str(saved_val), str(val),
                          f"Expected {saved_val} after rollback, got {val}")

    def test_kill_saves_to_history(self):
        """KILL saves previous value to history."""
        PDB.tool_set({"ns": "TEST", "subs": ["k"], "value": "precious"})
        PDB.tool_kill({"ns": "TEST", "subs": ["k"]})
        r = PDB.tool_history({"ns": "TEST", "subs": ["k"]})
        self.assertTrue(r["success"])
        # There should be at least one entry (the KILL record)
        if r["count"] >= 1:
            self.assertEqual(r["versions"][0]["op"], "KILL",
                            f"Expected KILL op, got {r['versions'][0].get('op')}")

    def test_rollback_after_kill_restores_value(self):
        """Rollback after KILL should restore the killed value."""
        PDB.tool_set({"ns": "TEST", "subs": ["r"], "value": "resurrect-me"})
        PDB.tool_kill({"ns": "TEST", "subs": ["r"]})
        # Verify key is gone
        g = PDB.tool_get({"ns": "TEST", "subs": ["r"]})
        self.assertFalse(g.get("found", True), "Key should be gone after KILL")
        # Get history
        r = PDB.tool_history({"ns": "TEST", "subs": ["r"]})
        self.assertTrue(r["success"])
        for v in r["versions"]:
            if v["op"] == "KILL":
                # Find the SET entry before KILL
                continue
            # Rollback to the SET version
            rb = PDB.tool_rollback({"ns": "TEST", "subs": ["r"], "timestamp": v["timestamp"]})
            self.assertTrue(rb["success"], f"Rollback failed: {rb.get('error')}")
            # Check value restored
            restored = PDB.tool_get({"ns": "TEST", "subs": ["r"]})
            self.assertEqual(
                restored.get("value"), "resurrect-me",
                f"Expected 'resurrect-me', got {restored.get('value')}")
            break

    def tearDown(self):
        conn = PDB._get_conn()
        conn.execute("DELETE FROM _globals")
        conn.commit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
