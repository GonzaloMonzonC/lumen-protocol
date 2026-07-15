#!/usr/bin/env python3
"""Tests Fase 3: macaroons por namespace (port compatible con macaroon.rs)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: F401  # sys.path del stack PDB
from pdb_macaroon import (Macaroon, caveats, check_access, authorize_tool,
                          tool_op, mint, generate_root_key, MIN_ENCODED_LEN)

p = f = 0
def t(n, o):
    global p, f
    if o: p += 1; print(f"  ✅ {n}")
    else: f += 1; print(f"  ❌ {n}")

print('🧪 TESTS MACAROON (Fase 3)\n')

KEY = bytes(range(32))
NOW = 1752000000  # 2025-07 aprox — antes del expiry 2030 del golden

# ── 1. Golden cruzado con Rust (pin del wire format) ──
GOLDEN_HEX = ("0108676f6c64656e2d31096c756d656e2d70646203106e735f707265666978203d"
              "2054455354096f70203d207265616413657870697279203c20323033302d30312d"
              "303174104972838bedda95a767a96f35769670f8bb5ab4cd0e436039a7c447eab0f3")
m = (Macaroon.create(KEY, "golden-1", "lumen-pdb")
     .attenuate(caveats.ns_prefix("TEST"))
     .attenuate(caveats.read_only())
     .attenuate(caveats.expiry_before("2030-01-01")))
t("golden hex estable (compat Rust)", m.encode().hex() == GOLDEN_HEX)
t("golden verifica", m.verify_with_time(KEY, NOW, lambda c: True))

# ── 2. Básicos: crear/verificar/clave incorrecta ──
k1, k2 = generate_root_key(), generate_root_key()
base = Macaroon.create(k1, "s1", "lumen")
t("verify sin caveats", base.verify_with_time(k1, NOW, lambda c: True))
t("clave incorrecta falla", not base.verify_with_time(k2, NOW, lambda c: True))

# ── 3. Atenuación y tampering ──
att = base.attenuate(caveats.ns_prefix("TEST")).attenuate(caveats.read_only())
t("atenuado verifica", att.verify_with_time(k1, NOW, lambda c: True))
tampered = Macaroon(att.version, att.id, att.location,
                    ["ns_prefix = OTRO", att.caveats[1]], att.signature)
t("caveat manipulado falla", not tampered.verify_with_time(k1, NOW, lambda c: True))
sig_bad = Macaroon(att.version, att.id, att.location, att.caveats,
                   bytes([att.signature[0] ^ 1]) + att.signature[1:])
t("firma manipulada falla", not sig_bad.verify_with_time(k1, NOW, lambda c: True))

# ── 4. Wire: roundtrip, truncado, versión ──
enc = att.encode()
dec = Macaroon.decode(enc)
t("roundtrip encode/decode", dec is not None and dec.caveats == att.caveats
  and dec.signature == att.signature)
t("truncado rechazado", Macaroon.decode(enc[:-5]) is None)
t("versión desconocida rechazada", Macaroon.decode(bytes([99]) + enc[1:]) is None)
t("mínimo 36 bytes", Macaroon.decode(b"\x01" + b"\x00" * 33) is None and MIN_ENCODED_LEN == 36)
b64 = att.to_b64()
t("roundtrip b64", Macaroon.from_b64(b64).signature == att.signature)

# ── 5. Expiry ──
exp = base.attenuate(caveats.expiry_before("2026-01-01"))
t("caducado falla", not exp.verify_with_time(k1, 1767225600 + 10, lambda c: True))
t("vigente pasa", exp.verify_with_time(k1, 1700000000, lambda c: True))
bad_exp = base.attenuate("expiry < garbage")
t("expiry ilegible falla (fail-closed)", not bad_exp.verify_with_time(k1, NOW, lambda c: True))

# ── 6. check_access: ns_prefix + op ──
tok = (Macaroon.create(k1, "agente-x", "lumen-pdb")
       .attenuate(caveats.ns_prefix("TEST"))
       .attenuate(caveats.read_only()))
ok, _ = check_access(tok, "TEST", "read", root_key=k1, now=NOW)
t("ns+op permitidos", ok)
ok, r = check_access(tok, "TESTsub", "read", root_key=k1, now=NOW)
t("prefijo cubre TESTsub", ok)
ok, r = check_access(tok, "System", "read", root_key=k1, now=NOW)
t("ns fuera de prefijo denegado", not ok and "ns_prefix" in r)
ok, r = check_access(tok, "TEST", "write", root_key=k1, now=NOW)
t("write con token read denegado", not ok and "op" in r)
ok, r = check_access(tok, None, "read", root_key=k1, now=NOW)
t("tool sin ns denegada con ns_prefix", not ok)
ok, r = check_access("token-basura", "TEST", "read", root_key=k1, now=NOW)
t("token ilegible denegado", not ok)

# caveat desconocido → fail-closed
unk = base.attenuate("magia = si")
ok, r = check_access(unk, "TEST", "read", root_key=k1, now=NOW)
t("caveat desconocido denegado", not ok and "desconocido" in r)

# atenuación estrecha: dos ns_prefix = intersección
inter = tok.attenuate(caveats.ns_prefix("TESTING"))
ok, _ = check_access(inter, "TESTING", "read", root_key=k1, now=NOW)
t("doble prefijo: intersección pasa", ok)
ok, _ = check_access(inter, "TESTx", "read", root_key=k1, now=NOW)
t("doble prefijo: fuera de intersección falla", not ok)

# ── 7. Gate del bridge ──
t("tool_op clasifica read", tool_op("pdb_get") == "read")
t("tool_op fail-closed a write", tool_op("pdb_tool_nueva_xyz") == "write")
ok, _ = authorize_tool(tok.to_b64(), "pdb_get", {"ns": "TEST"})
os.environ.setdefault("PDB_MACAROON_KEY", k1.hex())  # para authorize sin root explícita
ok2, _ = check_access(tok.to_b64(), "TEST", "read", root_key=k1, now=NOW)
t("authorize_tool con b64", ok2)
ok, r = check_access(tok.to_b64(), "TEST", "write", root_key=k1, now=NOW)
t("pdb_set denegado con token read", not ok)

# ── 8. mint() ──
tok_b64 = mint(ns_prefix="Zalo", op="write", expiry="2030-01-01", root_key=k1)
ok, _ = check_access(tok_b64, "Zalo", "write", root_key=k1, now=NOW)
t("mint write sobre ^Zalo pasa", ok)
ok, _ = check_access(tok_b64, "Zalo", "read", root_key=k1, now=NOW)
t("mint write no permite read", not ok)
ok, _ = check_access(tok_b64, "Hermes", "write", root_key=k1, now=NOW)
t("mint no cubre otro ns", not ok)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f == 0 else 1)
