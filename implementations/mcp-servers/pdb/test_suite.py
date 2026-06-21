#!/usr/bin/env python3
"""Test suite for PDBM-Lumen tools."""

from __future__ import annotations
import json, os, sys, tempfile, unittest

import pdb_tools as PDB


class TestEncoding(unittest.TestCase):

    def test_encode_decode_roundtrip(self):
        cases = [
            (["PATIENT", 1001, "name"], ["PATIENT", 1001.0, "name"]),
            (["x", -5, "y"], ["x", -5.0, "y"]),
            (["cfg", "theme", "dark"], ["cfg", "theme", "dark"]),
            ([42], [42.0]),
            ([0, 0.0, -0.0], [0.0, 0.0, 0.0]),
        ]
        for subs_in, subs_expected in cases:
            key = PDB.encode_subkey(subs_in)
            decoded = PDB.decode_subkey(key)
            self.assertEqual(decoded, subs_expected, f"Roundtrip: {subs_in}")

    def test_collation_order(self):
        k1 = PDB.encode_subkey(["a", 1])
        k2 = PDB.encode_subkey(["a", 2])
        k3 = PDB.encode_subkey(["a", 10])
        self.assertLess(k1, k2)
        self.assertLess(k2, k3)

        k_aa = PDB.encode_subkey(["a", "aa"])
        k_ab = PDB.encode_subkey(["a", "ab"])
        k_ba = PDB.encode_subkey(["a", "ba"])
        self.assertLess(k_aa, k_ab)
        self.assertLess(k_ab, k_ba)

        k_num = PDB.encode_subkey(["a", 100])
        k_str = PDB.encode_subkey(["a", "hello"])
        self.assertLess(k_num, k_str, "Numerics should sort before strings")

        k_empty = PDB.encode_subkey(["a", ""])
        k_zero = PDB.encode_subkey(["a", 0])
        self.assertLess(k_empty, k_zero)

        k_neg = PDB.encode_subkey(["a", -5])
        k_neg2 = PDB.encode_subkey(["a", -1])
        k_pos = PDB.encode_subkey(["a", 3])
        self.assertLess(k_neg, k_neg2)
        self.assertLess(k_neg, k_pos)

    def test_count_and_extract(self):
        key = PDB.encode_subkey(["PATIENT", 1001, "visits", 5, "dx"])
        self.assertEqual(PDB.count_levels(key), 5)
        self.assertEqual(PDB.extract_level(key, 0), "PATIENT")
        self.assertEqual(PDB.extract_level(key, 1), 1001.0)
        self.assertEqual(PDB.extract_level(key, 2), "visits")
        self.assertEqual(PDB.extract_level(key, 3), 5.0)
        self.assertEqual(PDB.extract_level(key, 4), "dx")
        self.assertIsNone(PDB.extract_level(key, 5))


class TestTools(unittest.TestCase):

    def _reset_db(self):
        with PDB._conn_lock:
            if PDB._conn is not None:
                try:
                    PDB._conn.close()
                except Exception:
                    pass
                PDB._conn = None
        PDB._DB_PATH = tempfile.mktemp(suffix=".db")

    def setUp(self):
        self._reset_db()

    def test_set_and_get(self):
        r = PDB.tool_set({"ns": "PATIENT", "subs": [42, "name"], "value": "Juan"})
        self.assertTrue(r["success"])

        r = PDB.tool_get({"ns": "PATIENT", "subs": [42, "name"]})
        self.assertTrue(r["success"])
        self.assertEqual(r["value"], "Juan")

        r = PDB.tool_get({"ns": "PATIENT", "subs": [99]})
        self.assertEqual(r["value"], None)
        self.assertFalse(r.get("found", True))

        r = PDB.tool_get({"ns": "PATIENT", "subs": [99], "default": "N/A"})
        self.assertEqual(r["value"], "N/A")

        r = PDB.tool_set({"ns": "PATIENT", "subs": [42, "age"], "value": 35})
        self.assertTrue(r["success"])
        r = PDB.tool_get({"ns": "PATIENT", "subs": [42, "age"]})
        self.assertEqual(r["value"], 35)

        r = PDB.tool_set({"ns": "PATIENT", "subs": [42, "address"], "value": {"city": "Tarragona", "zip": 43001}})
        self.assertTrue(r["success"])
        r = PDB.tool_get({"ns": "PATIENT", "subs": [42, "address"]})
        self.assertEqual(r["value"]["city"], "Tarragona")

        r = PDB.tool_set({"ns": "PATIENT", "subs": [42], "value": None})
        self.assertTrue(r["success"])
        r = PDB.tool_get({"ns": "PATIENT", "subs": [42]})
        self.assertIsNone(r["value"])

    def test_order(self):
        data = [
            (["Caballero", "Garcia", "Juan"], 1),
            (["Caballero", "Garcia", "Maria"], 2),
            (["Caballero", "Lopez", "Ana"], 3),
            (["Martinez", "Perez", "Luis"], 4),
        ]
        for subs, pid in data:
            PDB.tool_set({"ns": "PATIENT_I2", "subs": subs, "value": pid})

        # First at level 0
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": [""], "direction": 1})
        self.assertEqual(r["value"], "Caballero")

        # Next at level 0
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero"], "direction": 1})
        self.assertEqual(r["value"], "Martinez")

        # No more at level 0
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Martinez"], "direction": 1})
        self.assertIsNone(r["value"])

        # First under Caballero (level 1)
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", ""], "direction": 1})
        self.assertEqual(r["value"], "Garcia")

        # Next under Caballero
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", "Garcia"], "direction": 1})
        self.assertEqual(r["value"], "Lopez")

        # No more under Caballero
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", "Lopez"], "direction": 1})
        self.assertIsNone(r["value"])

        # First under Caballero/Garcia (level 2)
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", "Garcia", ""], "direction": 1})
        self.assertEqual(r["value"], "Juan")

        # Next under Caballero/Garcia
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", "Garcia", "Juan"], "direction": 1})
        self.assertEqual(r["value"], "Maria")

        # No more under Caballero/Garcia
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", "Garcia", "Maria"], "direction": 1})
        self.assertIsNone(r["value"])

        # Backward order
        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", ""], "direction": -1})
        self.assertEqual(r["value"], "Lopez")

        r = PDB.tool_order({"ns": "PATIENT_I2", "subs": ["Caballero", "Lopez"], "direction": -1})
        self.assertEqual(r["value"], "Garcia")

    def test_data(self):
        PDB.tool_set({"ns": "ORDERS", "subs": [1], "value": None})
        PDB.tool_set({"ns": "ORDERS", "subs": [1, "item"], "value": "widget"})

        r = PDB.tool_data({"ns": "ORDERS", "subs": [999]})
        self.assertEqual(r["value"], 0)

        # Value only, no children yet
        r = PDB.tool_data({"ns": "ORDERS", "subs": [1, "item"]})
        self.assertEqual(r["value"], 1)

        # Add child and re-check
        PDB.tool_set({"ns": "ORDERS", "subs": [1, "item", "qty"], "value": 5})
        r = PDB.tool_data({"ns": "ORDERS", "subs": [1, "item"]})
        self.assertEqual(r["value"], 11)

        # Structural node (no value, has children)
        r = PDB.tool_data({"ns": "ORDERS", "subs": [1]})
        self.assertEqual(r["value"], 10)

        # Value + children
        PDB.tool_set({"ns": "ORDERS", "subs": [2], "value": "express"})
        PDB.tool_set({"ns": "ORDERS", "subs": [2, "note"], "value": "fragile"})
        r = PDB.tool_data({"ns": "ORDERS", "subs": [2]})
        self.assertEqual(r["value"], 11)

    def test_kill(self):
        PDB.tool_set({"ns": "TMP", "subs": [1, "a"], "value": "x"})
        PDB.tool_set({"ns": "TMP", "subs": [1, "a", "deep"], "value": "y"})
        PDB.tool_set({"ns": "TMP", "subs": [1, "b"], "value": "z"})

        r = PDB.tool_kill({"ns": "TMP", "subs": [1, "a"]})
        self.assertTrue(r["success"])

        r = PDB.tool_get({"ns": "TMP", "subs": [1, "a"]})
        self.assertIsNone(r["value"])
        self.assertFalse(r.get("found", True))

        r = PDB.tool_get({"ns": "TMP", "subs": [1, "a", "deep"]})
        self.assertIsNone(r["value"])

        r = PDB.tool_get({"ns": "TMP", "subs": [1, "b"]})
        self.assertEqual(r["value"], "z")

    def test_incr(self):
        r = PDB.tool_incr({"ns": "COUNTER", "subs": ["visits"], "increment": 1})
        self.assertEqual(r["value"], 1)

        r = PDB.tool_incr({"ns": "COUNTER", "subs": ["visits"], "increment": 5})
        self.assertEqual(r["value"], 6)

        r = PDB.tool_incr({"ns": "COUNTER", "subs": ["visits"], "increment": -1})
        self.assertEqual(r["value"], 5)

        r = PDB.tool_incr({"ns": "COUNTER", "subs": ["orders"], "increment": 1})
        self.assertEqual(r["value"], 1)

    def test_merge(self):
        PDB.tool_set({"ns": "SRC", "subs": [1, "name"], "value": "Juan"})
        PDB.tool_set({"ns": "SRC", "subs": [1, "age"], "value": 30})
        PDB.tool_set({"ns": "SRC", "subs": [1, "scores", "math"], "value": 95})

        r = PDB.tool_merge({"target_ns": "DST", "target_subs": [100], "source_ns": "SRC", "source_subs": [1]})
        self.assertTrue(r["success"])

        r = PDB.tool_get({"ns": "DST", "subs": [100, "name"]})
        self.assertEqual(r["value"], "Juan")
        r = PDB.tool_get({"ns": "DST", "subs": [100, "age"]})
        self.assertEqual(r["value"], 30)
        r = PDB.tool_get({"ns": "DST", "subs": [100, "scores", "math"]})
        self.assertEqual(r["value"], 95)

    def test_query(self):
        PDB.tool_set({"ns": "LOG", "subs": ["2024-01-15", "10:00", "event"], "value": "login"})
        PDB.tool_set({"ns": "LOG", "subs": ["2024-01-15", "10:05", "event"], "value": "search"})
        PDB.tool_set({"ns": "LOG", "subs": ["2024-01-16", "09:00", "event"], "value": "logout"})

        r = PDB.tool_query({"sql": "SELECT count(*) as cnt FROM _globals WHERE ns='LOG'"})
        self.assertTrue(r["success"])
        self.assertEqual(r["rows"][0]["cnt"], 3)

        r = PDB.tool_query({"sql": "SELECT * FROM _globals WHERE ns=? LIMIT 2", "params": ["LOG"]})
        self.assertEqual(len(r["rows"]), 2)

    def test_schema(self):
        PDB.tool_set({"ns": "TEST", "subs": ["a"], "value": 1})
        PDB.tool_set({"ns": "TEST", "subs": ["b"], "value": 2})

        r = PDB.tool_schema()
        self.assertTrue(r["success"])
        nss = {ns["ns"]: ns for ns in r["namespaces"]}
        self.assertIn("TEST", nss)
        self.assertEqual(nss["TEST"]["nodes"], 2)

    def test_backup(self):
        PDB.tool_set({"ns": "BK", "subs": ["x"], "value": "data"})

        r = PDB.tool_backup()
        self.assertTrue(r["success"])
        self.assertIn("total_nodes", r)
        self.assertGreater(r["total_nodes"], 0)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            bkp = f.name
        try:
            r = PDB.tool_backup(bkp)
            self.assertTrue(r["success"])
            self.assertGreater(r["size_bytes"], 0)
        finally:
            if os.path.exists(bkp):
                os.unlink(bkp)


class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        with PDB._conn_lock:
            if PDB._conn is not None:
                try:
                    PDB._conn.close()
                except Exception:
                    pass
                PDB._conn = None
        PDB._DB_PATH = tempfile.mktemp(suffix=".db")

    def test_deeply_nested(self):
        subs = ["l0", "l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9"]
        PDB.tool_set({"ns": "DEEP", "subs": subs, "value": "bottom"})
        r = PDB.tool_get({"ns": "DEEP", "subs": subs})
        self.assertEqual(r["value"], "bottom")
        key = PDB.encode_subkey(subs)
        self.assertEqual(PDB.count_levels(key), 10)

    def test_unicode_subscripts(self):
        PDB.tool_set({"ns": "UNI", "subs": ["ñóa", "日本語", "😀"], "value": "unicode-test"})
        r = PDB.tool_get({"ns": "UNI", "subs": ["ñóa", "日本語", "😀"]})
        self.assertEqual(r["value"], "unicode-test")

    def test_empty_namespace(self):
        r = PDB.tool_get({"ns": "EMPTY", "subs": ["x"]})
        self.assertIsNone(r["value"])

        r = PDB.tool_order({"ns": "EMPTY", "subs": [""], "direction": 1})
        self.assertIsNone(r["value"])

    def test_large_value(self):
        large = "x" * 10000
        PDB.tool_set({"ns": "LARGE", "subs": ["data"], "value": large})
        r = PDB.tool_get({"ns": "LARGE", "subs": ["data"]})
        self.assertEqual(r["value"], large)


if __name__ == "__main__":
    unittest.main(verbosity=2)
