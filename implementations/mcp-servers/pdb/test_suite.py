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
        r = PDB.tool_set("PATIENT", [42, "name"], "Juan")
        self.assertTrue(r["success"])

        r = PDB.tool_get("PATIENT", [42, "name"])
        self.assertTrue(r["success"])
        self.assertEqual(r["value"], "Juan")

        r = PDB.tool_get("PATIENT", [99])
        self.assertEqual(r["value"], None)
        self.assertFalse(r.get("found", True))

        r = PDB.tool_get("PATIENT", [99], default="N/A")
        self.assertEqual(r["value"], "N/A")

        r = PDB.tool_set("PATIENT", [42, "age"], 35)
        self.assertTrue(r["success"])
        r = PDB.tool_get("PATIENT", [42, "age"])
        self.assertEqual(r["value"], 35)

        r = PDB.tool_set("PATIENT", [42, "address"], {"city": "Tarragona", "zip": 43001})
        self.assertTrue(r["success"])
        r = PDB.tool_get("PATIENT", [42, "address"])
        self.assertEqual(r["value"]["city"], "Tarragona")

        r = PDB.tool_set("PATIENT", [42], None)
        self.assertTrue(r["success"])
        r = PDB.tool_get("PATIENT", [42])
        self.assertIsNone(r["value"])

    def test_order(self):
        data = [
            (["Caballero", "Garcia", "Juan"], 1),
            (["Caballero", "Garcia", "Maria"], 2),
            (["Caballero", "Lopez", "Ana"], 3),
            (["Martinez", "Perez", "Luis"], 4),
        ]
        for subs, pid in data:
            PDB.tool_set("PATIENT_I2", subs, pid)

        # First at level 0
        r = PDB.tool_order("PATIENT_I2", [""], 1)
        self.assertEqual(r["value"], "Caballero")

        # Next at level 0
        r = PDB.tool_order("PATIENT_I2", ["Caballero"], 1)
        self.assertEqual(r["value"], "Martinez")

        # No more at level 0
        r = PDB.tool_order("PATIENT_I2", ["Martinez"], 1)
        self.assertIsNone(r["value"])

        # First under Caballero (level 1)
        r = PDB.tool_order("PATIENT_I2", ["Caballero", ""], 1)
        self.assertEqual(r["value"], "Garcia")

        # Next under Caballero
        r = PDB.tool_order("PATIENT_I2", ["Caballero", "Garcia"], 1)
        self.assertEqual(r["value"], "Lopez")

        # No more under Caballero
        r = PDB.tool_order("PATIENT_I2", ["Caballero", "Lopez"], 1)
        self.assertIsNone(r["value"])

        # First under Caballero/Garcia (level 2)
        r = PDB.tool_order("PATIENT_I2", ["Caballero", "Garcia", ""], 1)
        self.assertEqual(r["value"], "Juan")

        # Next under Caballero/Garcia
        r = PDB.tool_order("PATIENT_I2", ["Caballero", "Garcia", "Juan"], 1)
        self.assertEqual(r["value"], "Maria")

        # No more under Caballero/Garcia
        r = PDB.tool_order("PATIENT_I2", ["Caballero", "Garcia", "Maria"], 1)
        self.assertIsNone(r["value"])

        # Backward order
        r = PDB.tool_order("PATIENT_I2", ["Caballero", ""], -1)
        self.assertEqual(r["value"], "Lopez")

        r = PDB.tool_order("PATIENT_I2", ["Caballero", "Lopez"], -1)
        self.assertEqual(r["value"], "Garcia")

    def test_data(self):
        PDB.tool_set("ORDERS", [1], None)
        PDB.tool_set("ORDERS", [1, "item"], "widget")

        r = PDB.tool_data("ORDERS", [999])
        self.assertEqual(r["value"], 0)

        # Value only, no children yet
        r = PDB.tool_data("ORDERS", [1, "item"])
        self.assertEqual(r["value"], 1)

        # Add child and re-check
        PDB.tool_set("ORDERS", [1, "item", "qty"], 5)
        r = PDB.tool_data("ORDERS", [1, "item"])
        self.assertEqual(r["value"], 11)

        # Structural node (no value, has children)
        r = PDB.tool_data("ORDERS", [1])
        self.assertEqual(r["value"], 10)

        # Value + children
        PDB.tool_set("ORDERS", [2], "express")
        PDB.tool_set("ORDERS", [2, "note"], "fragile")
        r = PDB.tool_data("ORDERS", [2])
        self.assertEqual(r["value"], 11)

    def test_kill(self):
        PDB.tool_set("TMP", [1, "a"], "x")
        PDB.tool_set("TMP", [1, "a", "deep"], "y")
        PDB.tool_set("TMP", [1, "b"], "z")

        r = PDB.tool_kill("TMP", [1, "a"])
        self.assertTrue(r["success"])

        r = PDB.tool_get("TMP", [1, "a"])
        self.assertIsNone(r["value"])
        self.assertFalse(r.get("found", True))

        r = PDB.tool_get("TMP", [1, "a", "deep"])
        self.assertIsNone(r["value"])

        r = PDB.tool_get("TMP", [1, "b"])
        self.assertEqual(r["value"], "z")

    def test_incr(self):
        r = PDB.tool_incr("COUNTER", ["visits"], 1)
        self.assertEqual(r["value"], 1)

        r = PDB.tool_incr("COUNTER", ["visits"], 5)
        self.assertEqual(r["value"], 6)

        r = PDB.tool_incr("COUNTER", ["visits"], -1)
        self.assertEqual(r["value"], 5)

        r = PDB.tool_incr("COUNTER", ["orders"], 1)
        self.assertEqual(r["value"], 1)

    def test_merge(self):
        PDB.tool_set("SRC", [1, "name"], "Juan")
        PDB.tool_set("SRC", [1, "age"], 30)
        PDB.tool_set("SRC", [1, "scores", "math"], 95)

        r = PDB.tool_merge("DST", [100], "SRC", [1])
        self.assertTrue(r["success"])

        r = PDB.tool_get("DST", [100, "name"])
        self.assertEqual(r["value"], "Juan")
        r = PDB.tool_get("DST", [100, "age"])
        self.assertEqual(r["value"], 30)
        r = PDB.tool_get("DST", [100, "scores", "math"])
        self.assertEqual(r["value"], 95)

    def test_query(self):
        PDB.tool_set("LOG", ["2024-01-15", "10:00", "event"], "login")
        PDB.tool_set("LOG", ["2024-01-15", "10:05", "event"], "search")
        PDB.tool_set("LOG", ["2024-01-16", "09:00", "event"], "logout")

        r = PDB.tool_query("SELECT count(*) as cnt FROM _globals WHERE ns='LOG'")
        self.assertTrue(r["success"])
        self.assertEqual(r["rows"][0]["cnt"], 3)

        r = PDB.tool_query("SELECT * FROM _globals WHERE ns=? LIMIT 2", params=["LOG"])
        self.assertEqual(len(r["rows"]), 2)

    def test_schema(self):
        PDB.tool_set("TEST", ["a"], 1)
        PDB.tool_set("TEST", ["b"], 2)

        r = PDB.tool_schema()
        self.assertTrue(r["success"])
        nss = {ns["ns"]: ns for ns in r["namespaces"]}
        self.assertIn("TEST", nss)
        self.assertEqual(nss["TEST"]["nodes"], 2)

    def test_backup(self):
        PDB.tool_set("BK", ["x"], "data")

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
        PDB.tool_set("DEEP", subs, "bottom")
        r = PDB.tool_get("DEEP", subs)
        self.assertEqual(r["value"], "bottom")
        key = PDB.encode_subkey(subs)
        self.assertEqual(PDB.count_levels(key), 10)

    def test_unicode_subscripts(self):
        PDB.tool_set("UNI", ["ñóa", "日本語", "😀"], "unicode-test")
        r = PDB.tool_get("UNI", ["ñóa", "日本語", "😀"])
        self.assertEqual(r["value"], "unicode-test")

    def test_empty_namespace(self):
        r = PDB.tool_get("EMPTY", ["x"])
        self.assertIsNone(r["value"])

        r = PDB.tool_order("EMPTY", [""], 1)
        self.assertIsNone(r["value"])

    def test_large_value(self):
        large = "x" * 10000
        PDB.tool_set("LARGE", ["data"], large)
        r = PDB.tool_get("LARGE", ["data"])
        self.assertEqual(r["value"], large)


if __name__ == "__main__":
    unittest.main(verbosity=2)
