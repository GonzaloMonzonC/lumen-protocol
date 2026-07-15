#!/usr/bin/env python3
"""
pdb_macaroon.py — macaroons para PDB (Fase 3): capacidades por namespace.

Port 1:1 de implementations/rust/src/macaroon.rs (mismo wire format,
misma cadena HMAC-SHA256) — un token emitido en Rust verifica en Python
y viceversa (test golden cruzado en implementations/rust/tests/).

Cadena de firma:
    sig = HMAC-SHA256(root_key, id)
    por cada caveat: sig = HMAC-SHA256(sig, caveat)

Wire format (idéntico a macaroon.rs):
    [version:u8][id_len:u8][id][loc_len:u8][loc]
    [caveat_count:u8]([c_len:u8][caveat])*[signature:32]

Caveats PDB (Fase 3):
    ns_prefix = <prefijo>   → el ns accedido debe empezar por <prefijo>
    op = read | op = write  → restringe la clase de operación
    expiry < <ISO8601>      → auto-verificado contra el reloj
    tool = <nombre>         → restringe a una tool concreta

Fail-closed: un caveat desconocido invalida el token.

CLI:
    python3 pdb_macaroon.py keygen
    python3 pdb_macaroon.py mint --ns TEST --op read [--expiry 2026-12-31]
    python3 pdb_macaroon.py inspect <token_b64>
    python3 pdb_macaroon.py verify <token_b64> --ns TEST --op read
"""

import base64
import hashlib
import hmac as _hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MACAROON_V1 = 1
SIGNATURE_SIZE = 32
MAX_CAVEAT_LEN = 255
MAX_CAVEATS = 32
MIN_ENCODED_LEN = 1 + 1 + 1 + 1 + SIGNATURE_SIZE  # 36 (el doc de macaroon.rs dice 35, pero su constante también computa 36)

KEY_FILE = Path(os.path.expanduser("~/.hermes/pdb-macaroon.key"))


def _hmac_sha256(key: bytes, message: bytes) -> bytes:
    return _hmac.new(key, message, hashlib.sha256).digest()


def _parse_iso8601_to_unix(s: str):
    """Equivalente al parser simplificado de macaroon.rs:
    'YYYY-MM-DD' o 'YYYY-MM-DDTHH:MM:SS[Z]', asumido UTC."""
    s = s.strip()
    if len(s) < 10:
        return None
    try:
        if len(s) >= 19 and s[10] == "T":
            dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        else:
            dt = datetime.strptime(s[:10], "%Y-%m-%d")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


class Macaroon:
    __slots__ = ("version", "id", "location", "caveats", "signature")

    def __init__(self, version, id, location, caveats, signature):
        self.version = version
        self.id = id
        self.location = location
        self.caveats = caveats
        self.signature = signature

    # ── Creación / atenuación ──

    @classmethod
    def create(cls, root_key: bytes, id: str, location: str) -> "Macaroon":
        assert len(root_key) == 32, "root_key debe ser de 32 bytes"
        sig = _hmac_sha256(root_key, id.encode())
        return cls(MACAROON_V1, id, location, [], sig)

    def attenuate(self, caveat: str) -> "Macaroon":
        sig = _hmac_sha256(self.signature, caveat.encode())
        return Macaroon(self.version, self.id, self.location,
                        self.caveats + [caveat], sig)

    # ── Verificación ──

    def verify_with_time(self, root_key: bytes, now: int, check_caveat) -> bool:
        for caveat in self.caveats:
            expiry_str = caveats.parse_expiry(caveat)
            if expiry_str is not None:
                expiry_ts = _parse_iso8601_to_unix(expiry_str)
                if expiry_ts is None:
                    return False  # expiry ilegible → rechazar
                if now >= expiry_ts:
                    return False  # caducado
                continue
            if not check_caveat(caveat):
                return False
        sig = _hmac_sha256(root_key, self.id.encode())
        for caveat in self.caveats:
            sig = _hmac_sha256(sig, caveat.encode())
        return _hmac.compare_digest(sig, self.signature)

    def verify(self, root_key: bytes, check_caveat) -> bool:
        return self.verify_with_time(root_key, int(time.time()), check_caveat)

    # ── Serialización ──

    def encode(self) -> bytes:
        idb = self.id.encode()[:255]
        locb = self.location.encode()[:255]
        buf = bytearray()
        buf.append(self.version)
        buf.append(len(idb))
        buf += idb
        buf.append(len(locb))
        buf += locb
        cavs = self.caveats[:MAX_CAVEATS]
        buf.append(len(cavs))
        for c in cavs:
            cb = c.encode()[:MAX_CAVEAT_LEN]
            buf.append(len(cb))
            buf += cb
        buf += self.signature
        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes):
        if len(data) < MIN_ENCODED_LEN:
            return None
        version = data[0]
        if version != MACAROON_V1:
            return None
        id_len = data[1]
        if len(data) < 2 + id_len:
            return None
        try:
            mid = data[2:2 + id_len].decode()
        except UnicodeDecodeError:
            return None
        pos = 2 + id_len
        if len(data) < pos + 1:
            return None
        loc_len = data[pos]
        if len(data) < pos + 1 + loc_len:
            return None
        try:
            loc = data[pos + 1:pos + 1 + loc_len].decode()
        except UnicodeDecodeError:
            return None
        pos = pos + 1 + loc_len
        if len(data) < pos + 1:
            return None
        count = data[pos]
        pos += 1
        cavs = []
        for _ in range(count):
            if len(data) < pos + 1:
                return None
            c_len = data[pos]
            pos += 1
            if len(data) < pos + c_len:
                return None
            try:
                cavs.append(data[pos:pos + c_len].decode())
            except UnicodeDecodeError:
                return None
            pos += c_len
        if len(data) < pos + SIGNATURE_SIZE:
            return None
        sig = data[pos:pos + SIGNATURE_SIZE]
        return cls(version, mid, loc, cavs, bytes(sig))

    # ── Base64 (transporte en headers/args) ──

    def to_b64(self) -> str:
        return base64.urlsafe_b64encode(self.encode()).decode()

    @classmethod
    def from_b64(cls, s: str):
        try:
            return cls.decode(base64.urlsafe_b64decode(s.encode()))
        except Exception:
            return None


# ── Caveat helpers (espejo de macaroon.rs::caveats + PDB) ──

class caveats:
    @staticmethod
    def method(name): return f"method = {name}"

    @staticmethod
    def expiry_before(ts): return f"expiry < {ts}"

    @staticmethod
    def tool(name): return f"tool = {name}"

    @staticmethod
    def read_only(): return "op = read"

    @staticmethod
    def write_only(): return "op = write"

    @staticmethod
    def ns_prefix(prefix): return f"ns_prefix = {prefix}"

    @staticmethod
    def parse_method(c):
        return c[len("method = "):] if c.startswith("method = ") else None

    @staticmethod
    def parse_expiry(c):
        return c[len("expiry < "):] if c.startswith("expiry < ") else None

    @staticmethod
    def parse_tool(c):
        return c[len("tool = "):] if c.startswith("tool = ") else None

    @staticmethod
    def parse_ns_prefix(c):
        return c[len("ns_prefix = "):] if c.startswith("ns_prefix = ") else None

    @staticmethod
    def parse_op(c):
        return c[len("op = "):] if c.startswith("op = ") else None

    @staticmethod
    def is_read_only(c): return c == "op = read"


# ── Root key ──

def generate_root_key() -> bytes:
    return os.urandom(32)


def load_root_key() -> bytes:
    """env PDB_MACAROON_KEY (hex de 64) > ~/.hermes/pdb-macaroon.key
    (se crea con permisos 600 si no existe)."""
    env = os.environ.get("PDB_MACAROON_KEY", "")
    if env:
        key = bytes.fromhex(env)
        assert len(key) == 32, "PDB_MACAROON_KEY debe ser hex de 64 chars"
        return key
    if KEY_FILE.exists():
        key = bytes.fromhex(KEY_FILE.read_text().strip())
        assert len(key) == 32
        return key
    key = generate_root_key()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.hex())
    KEY_FILE.chmod(0o600)
    return key


# ── Autorización PDB (Fase 3) ──

# Tools de solo lectura del bridge; todo lo demás es write (fail-closed)
READ_TOOLS = {
    "pdb_get", "pdb_order", "pdb_data", "pdb_query", "pdb_schema",
    "pdb_fts_search", "pdb_has", "pdb_history", "pdb_changes",
    "pdb_map_get", "pdb_map_list", "pdb_index_list", "pdb_trigger_list",
    "pdb_partition_list", "pdb_scratch_get", "pdb_mvm_list",
    "pdb_mvm_mailbox_read", "pdb_journal_status", "pdb_q_list",
    "pdb_embed_search", "pdb_vec_search", "pdb_event_route_list",
}


def tool_op(tool_name: str) -> str:
    return "read" if tool_name in READ_TOOLS else "write"


def check_access(token, ns, op, root_key=None, tool_name=None, now=None):
    """Verifica que un token autoriza (ns, op).

    token: Macaroon | b64 str. ns: namespace accedido (None si la tool no
    opera sobre un ns concreto — falla si el token tiene ns_prefix).
    op: "read" | "write".
    → (ok: bool, reason: str)
    """
    m = token if isinstance(token, Macaroon) else Macaroon.from_b64(token or "")
    if m is None:
        return False, "token ilegible"
    root_key = root_key or load_root_key()

    reason = []

    def check(c):
        p = caveats.parse_ns_prefix(c)
        if p is not None:
            if ns is None or not str(ns).startswith(p):
                reason.append(f"ns '{ns}' fuera de ns_prefix '{p}'")
                return False
            return True
        o = caveats.parse_op(c)
        if o is not None:
            if op != o:
                reason.append(f"op '{op}' no permitida (token: '{o}')")
                return False
            return True
        t = caveats.parse_tool(c)
        if t is not None:
            if tool_name != t:
                reason.append(f"tool '{tool_name}' no permitida (token: '{t}')")
                return False
            return True
        mth = caveats.parse_method(c)
        if mth is not None:
            return True  # caveat de método MCP: no aplica a nivel PDB
        reason.append(f"caveat desconocido: '{c}'")
        return False  # fail-closed

    ok = m.verify_with_time(root_key, now if now is not None else int(time.time()), check)
    if ok:
        return True, "ok"
    return False, reason[0] if reason else "firma inválida o token caducado"


def authorize_tool(token, tool_name, args):
    """Gate para el bridge: (ok, reason) para una tool call pdb_*."""
    ns = (args or {}).get("ns")
    return check_access(token, ns, tool_op(tool_name), tool_name=tool_name)


def mint(ns_prefix=None, op=None, expiry=None, id=None, location="lumen-pdb",
         root_key=None) -> str:
    """Emite un token atenuado. → b64."""
    root_key = root_key or load_root_key()
    m = Macaroon.create(root_key, id or f"pdb-{int(time.time())}", location)
    if ns_prefix:
        m = m.attenuate(caveats.ns_prefix(ns_prefix))
    if op:
        m = m.attenuate(f"op = {op}")
    if expiry:
        m = m.attenuate(caveats.expiry_before(expiry))
    return m.to_b64()


# ── CLI ──

def _main():
    import argparse
    p = argparse.ArgumentParser(description="Macaroons PDB (Fase 3)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen")
    mp = sub.add_parser("mint")
    mp.add_argument("--ns", help="ns_prefix")
    mp.add_argument("--op", choices=["read", "write"])
    mp.add_argument("--expiry", help="ISO8601: 2026-12-31 o 2026-12-31T23:59:59")
    mp.add_argument("--id", default=None)
    ip = sub.add_parser("inspect")
    ip.add_argument("token")
    vp = sub.add_parser("verify")
    vp.add_argument("token")
    vp.add_argument("--ns", required=True)
    vp.add_argument("--op", required=True, choices=["read", "write"])
    a = p.parse_args()

    if a.cmd == "keygen":
        key = generate_root_key()
        print(f"PDB_MACAROON_KEY={key.hex()}")
    elif a.cmd == "mint":
        print(mint(ns_prefix=a.ns, op=a.op, expiry=a.expiry, id=a.id))
    elif a.cmd == "inspect":
        m = Macaroon.from_b64(a.token)
        if not m:
            print("token ilegible"); sys.exit(1)
        print(json.dumps({"id": m.id, "location": m.location,
                          "caveats": m.caveats, "sig": m.signature.hex()[:16] + "…"},
                         indent=2, ensure_ascii=False))
    elif a.cmd == "verify":
        ok, reason = check_access(a.token, a.ns, a.op)
        print(f"{'✅' if ok else '❌'} {reason}")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    _main()
