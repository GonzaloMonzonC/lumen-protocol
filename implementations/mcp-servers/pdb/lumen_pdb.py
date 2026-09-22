#!/usr/bin/env python3
"""
lumen_pdb.py — wrapper ctypes del engine redb (crate lumen-pdb, Fase 4).

Flag de motor con fallback automático:
    engine = connect(path)               # PDB_ENGINE=redb|sqlite (default sqlite)
    engine.name                          # "redb" o "sqlite"
    engine.set("TEST", ["a", 1], "v")    # misma semántica en ambos
    engine.get("TEST", ["a", 1])
    engine.order("TEST", ["a", ""])      # $ORDER
    engine.data("TEST", ["a"])           # $DATA 0/1/10/11
    engine.kill("TEST", ["a"])           # nodo + subárbol
    engine.incr("CNT", ["n"], 2)
    engine.merge("DST", ["d"], "SRC", ["s"])

Si PDB_ENGINE=redb pero la dylib no está compilada/cargable, cae a
sqlite con un aviso (fallback automático del plan §Fase 4).

La codificación de subkeys es la MISMA (encode_subkey de pdb_tools =
subkey.rs, golden verificado), así que una BD redb es byte-compatible
en claves con la SQLite: el migrador (pdb_migrate.py) copia raw.
"""

import ctypes
import json
import os
import struct
import sys
import threading
from functools import cmp_to_key
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
from pdb_tools import _double_to_sortable, decode_subkey, encode_subkey  # noqa: E402

_REPO = _HERE.parent.parent.parent
_CRATE = _REPO / "implementations" / "rust" / "lumen-pdb"


def _lib_path():
    env = os.environ.get("LUMEN_PDB_LIB")
    if env:
        return Path(env)
    name = {"darwin": "liblumen_pdb.dylib", "linux": "liblumen_pdb.so"}.get(
        sys.platform, "lumen_pdb.dll")
    return _CRATE / "target" / "release" / name


def ensure_built(quiet=True) -> bool:
    """Compila la dylib si falta/está obsoleta y hay cargo."""
    p = _lib_path()
    external = bool(os.environ.get("LUMEN_PDB_LIB"))
    if p.exists():
        sources = [_CRATE / "Cargo.toml", _CRATE / "Cargo.lock"]
        sources += list((_CRATE / "src").glob("*.rs"))
        if external or all(src.stat().st_mtime <= p.stat().st_mtime
                           for src in sources if src.exists()):
            return True
    import shutil, subprocess
    if not shutil.which("cargo") or not _CRATE.exists():
        return False
    r = subprocess.run(["cargo", "build", "--release"], cwd=_CRATE,
                       capture_output=quiet, text=True)
    return r.returncode == 0 and p.exists()


_lib = None


def _load():
    global _lib
    if _lib is not None:
        return _lib
    p = _lib_path()
    if not p.exists() and not ensure_built():
        raise OSError(f"dylib no disponible: {p}")
    lib = ctypes.CDLL(str(p))
    lib.lp_open.restype = ctypes.c_void_p
    lib.lp_open.argtypes = [ctypes.c_char_p]
    lib.lp_close.argtypes = [ctypes.c_void_p]
    lib.lp_free.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    lib.lp_set.restype = ctypes.c_int
    lib.lp_set.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                           ctypes.c_char_p, ctypes.c_size_t,
                           ctypes.c_char_p, ctypes.c_size_t]
    lib.lp_set_many.restype = ctypes.c_int64
    lib.lp_set_many.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                ctypes.c_char_p, ctypes.c_size_t]
    lib.lp_get.restype = ctypes.c_int
    lib.lp_get.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                           ctypes.c_char_p, ctypes.c_size_t,
                           ctypes.POINTER(ctypes.c_void_p),
                           ctypes.POINTER(ctypes.c_size_t)]
    lib.lp_kill.restype = ctypes.c_int64
    lib.lp_kill.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                            ctypes.c_char_p, ctypes.c_size_t]
    lib.lp_data.restype = ctypes.c_int
    lib.lp_data.argtypes = lib.lp_kill.argtypes
    lib.lp_order.restype = ctypes.c_int
    lib.lp_order.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                             ctypes.c_char_p, ctypes.c_size_t,
                             ctypes.c_char_p, ctypes.c_size_t,
                             ctypes.c_int,
                             ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(ctypes.c_size_t)]
    lib.lp_incr.restype = ctypes.c_int
    lib.lp_incr.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                            ctypes.c_char_p, ctypes.c_size_t,
                            ctypes.c_double, ctypes.POINTER(ctypes.c_double)]
    lib.lp_merge.restype = ctypes.c_int64
    lib.lp_merge.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                             ctypes.c_char_p, ctypes.c_size_t,
                             ctypes.c_char_p,
                             ctypes.c_char_p, ctypes.c_size_t]
    lib.lp_count.restype = ctypes.c_int64
    lib.lp_count.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.lp_flush.restype = ctypes.c_int
    lib.lp_flush.argtypes = [ctypes.c_void_p]
    _lib = lib
    return lib


def available() -> bool:
    try:
        _load()
        return True
    except (OSError, AttributeError):
        return False


class RedbPDB:
    """Engine redb con la semántica de las 7 operaciones núcleo."""
    name = "redb"

    def __init__(self, path: str):
        self._lib = _load()
        self._h = self._lib.lp_open(str(path).encode())
        if not self._h:
            raise OSError(f"no se pudo abrir {path}")
        self.path = str(path)

    def close(self):
        if self._h:
            self._lib.lp_close(self._h)
            self._h = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ── helpers ──
    def _take_buf(self, pptr, plen) -> bytes:
        data = ctypes.string_at(pptr.value, plen.value)
        self._lib.lp_free(pptr, plen.value)
        return data

    # ── operaciones ──
    def set(self, ns, subs, value):
        key = encode_subkey(subs)
        val = json.dumps(value, ensure_ascii=False).encode()
        rc = self._lib.lp_set(self._h, ns.encode(), key, len(key), val, len(val))
        if rc != 0:
            raise RuntimeError(f"lp_set rc={rc}")
        return True

    def set_raw(self, ns, pairs):
        """Bulk: [(subkey_bytes, value_bytes)] en una transacción."""
        buf = bytearray()
        for k, v in pairs:
            buf += len(k).to_bytes(4, "little") + k
            buf += len(v).to_bytes(4, "little") + v
        n = self._lib.lp_set_many(self._h, ns.encode(), bytes(buf), len(buf))
        if n < 0:
            raise RuntimeError(f"lp_set_many rc={n}")
        return n

    def get(self, ns, subs, default=None):
        key = encode_subkey(subs)
        pptr = ctypes.c_void_p()
        plen = ctypes.c_size_t()
        rc = self._lib.lp_get(self._h, ns.encode(), key, len(key),
                              ctypes.byref(pptr), ctypes.byref(plen))
        if rc == 1:
            return default
        if rc != 0:
            raise RuntimeError(f"lp_get rc={rc}")
        raw_bytes = self._take_buf(pptr, plen)
        if not raw_bytes:  # sentinel de nodo estructural (SQLite NULL)
            return default
        raw = raw_bytes.decode()
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw

    def get_raw(self, ns, subkey):
        """Lee por clave ya codificada, sin transformar los bytes del valor."""
        pptr = ctypes.c_void_p()
        plen = ctypes.c_size_t()
        rc = self._lib.lp_get(self._h, ns.encode(), subkey, len(subkey),
                              ctypes.byref(pptr), ctypes.byref(plen))
        if rc == 1:
            return None
        if rc != 0:
            raise RuntimeError(f"lp_get rc={rc}")
        return self._take_buf(pptr, plen)

    def order(self, ns, subs, direction=1):
        """$ORDER: subs = padre + posición actual ('' = desde el borde)."""
        if not subs:
            raise ValueError("$ORDER necesita al menos un subscript")
        parent = encode_subkey(subs[:-1])
        current = subs[-1]
        cur_seg = b"" if current in ("", None) else encode_subkey([current])
        pptr = ctypes.c_void_p()
        plen = ctypes.c_size_t()
        rc = self._lib.lp_order(self._h, ns.encode(), parent, len(parent),
                                cur_seg, len(cur_seg), direction,
                                ctypes.byref(pptr), ctypes.byref(plen))
        if rc == 1:
            return None
        if rc != 0:
            raise RuntimeError(f"lp_order rc={rc}")
        seg = self._take_buf(pptr, plen)
        vals = decode_subkey(seg)
        return vals[0] if vals else None

    def data(self, ns, subs):
        key = encode_subkey(subs)
        rc = self._lib.lp_data(self._h, ns.encode(), key, len(key))
        if rc < 0:
            raise RuntimeError(f"lp_data rc={rc}")
        return rc

    def kill(self, ns, subs):
        key = encode_subkey(subs)
        n = self._lib.lp_kill(self._h, ns.encode(), key, len(key))
        if n < 0:
            raise RuntimeError(f"lp_kill rc={n}")
        return n

    def incr(self, ns, subs, delta=1):
        key = encode_subkey(subs)
        out = ctypes.c_double()
        rc = self._lib.lp_incr(self._h, ns.encode(), key, len(key),
                               float(delta), ctypes.byref(out))
        if rc != 0:
            raise RuntimeError(f"lp_incr rc={rc}")
        v = out.value
        return int(v) if v == int(v) else v

    def merge(self, dst_ns, dst_subs, src_ns, src_subs):
        dk = encode_subkey(dst_subs)
        sk = encode_subkey(src_subs)
        n = self._lib.lp_merge(self._h, dst_ns.encode(), dk, len(dk),
                               src_ns.encode(), sk, len(sk))
        if n < 0:
            raise RuntimeError(f"lp_merge rc={n}")
        return n

    def count(self, ns):
        n = self._lib.lp_count(self._h, ns.encode())
        if n < 0:
            raise RuntimeError(f"lp_count rc={n}")
        return n

    def flush(self):
        rc = self._lib.lp_flush(self._h)
        if rc != 0:
            raise RuntimeError(f"lp_flush rc={rc}")


class SqlitePDB:
    """Implementación SQLite del mismo contrato mínimo que :class:`RedbPDB`.

    Usa una conexión propia para que ``path=`` sea real y para que dos engines
    puedan compararse sin mutar ``PDB_PATH`` ni la conexión global de
    ``pdb_tools``. Esta capa cubre las siete operaciones núcleo; las extensiones
    SQLite (historial, triggers, particionado) siguen perteneciendo a
    ``pdb_tools``.
    """
    name = "sqlite"

    def __init__(self, path=None):
        from pdb_tools import _get_db_path, pdb_connect
        self.path = path or _get_db_path()
        self._lock = threading.RLock()
        self._con = pdb_connect(path=self.path, timeout=10)
        self._con.execute("""
            CREATE TABLE IF NOT EXISTS _globals (
                ns TEXT NOT NULL,
                subkey BLOB NOT NULL,
                value TEXT,
                PRIMARY KEY (ns, subkey)
            ) WITHOUT ROWID
        """)
        self._con.commit()

    def close(self):
        if self._con is not None:
            self._con.close()
            self._con = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @staticmethod
    def _value_bytes(raw):
        if raw is None:
            return None
        if isinstance(raw, bytes):
            return raw
        return str(raw).encode()

    @staticmethod
    def _subtree_hi(key):
        return key + b"\xff\xff\xff\xff"

    def set(self, ns, subs, value):
        key = encode_subkey(subs)
        raw = json.dumps(value, ensure_ascii=False).encode()
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                (ns, key, raw))
            self._con.commit()
        return True

    def set_raw(self, ns, pairs):
        """Bulk raw equivalente a ``lp_set_many``, en una transacción."""
        pairs = list(pairs)
        with self._lock:
            self._con.executemany(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                [(ns, key, value) for key, value in pairs])
            self._con.commit()
        return len(pairs)

    def get(self, ns, subs, default=None):
        raw = self.get_raw(ns, encode_subkey(subs))
        if raw is None:
            return default
        try:
            return json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return raw.decode(errors="replace")

    def get_raw(self, ns, subkey):
        with self._lock:
            row = self._con.execute(
                "SELECT value FROM _globals WHERE ns=? AND subkey=?",
                (ns, subkey)).fetchone()
        return None if row is None else self._value_bytes(row[0])

    def order(self, ns, subs, direction=1):
        if not subs:
            raise ValueError("$ORDER necesita al menos un subscript")
        parent_subs, current = subs[:-1], subs[-1]
        parent = encode_subkey(parent_subs)
        start = parent if current in ("", None) else encode_subkey(subs)
        op, ordering = (">", "ASC") if direction >= 0 else ("<", "DESC")
        if direction < 0 and current in ("", None):
            start = self._subtree_hi(parent)
        with self._lock:
            rows = self._con.execute(
                f"SELECT subkey FROM _globals WHERE ns=? AND subkey {op} ? "
                f"ORDER BY subkey {ordering}", (ns, start)).fetchall()
        level = len(parent_subs)
        for (subkey,) in rows:
            subkey = bytes(subkey)
            if parent and not subkey.startswith(parent):
                if direction >= 0:
                    break
                continue
            decoded = decode_subkey(subkey)
            if len(decoded) <= level:
                continue
            candidate = decoded[level]
            if (current not in ("", None)
                    and encode_subkey([candidate]) == encode_subkey([current])):
                continue
            return candidate
        return None

    def data(self, ns, subs):
        key = encode_subkey(subs)
        with self._lock:
            row = self._con.execute(
                "SELECT value FROM _globals WHERE ns=? AND subkey=?", (ns, key)
            ).fetchone()
            own = row is not None and row[0] is not None
            nxt = self._con.execute(
                "SELECT subkey FROM _globals WHERE ns=? AND subkey>? "
                "ORDER BY subkey LIMIT 1", (ns, key)).fetchone()
        child = bool(nxt and len(nxt[0]) > len(key)
                     and bytes(nxt[0]).startswith(key))
        return 11 if own and child else 1 if own else 10 if child else 0

    def kill(self, ns, subs):
        key, hi = encode_subkey(subs), self._subtree_hi(encode_subkey(subs))
        with self._lock:
            n = self._con.execute(
                "SELECT COUNT(*) FROM _globals WHERE ns=? AND "
                "(subkey=? OR (subkey>? AND subkey<?))",
                (ns, key, key, hi)).fetchone()[0]
            self._con.execute(
                "DELETE FROM _globals WHERE ns=? AND "
                "(subkey=? OR (subkey>? AND subkey<?))",
                (ns, key, key, hi))
            self._con.commit()
        return n

    def incr(self, ns, subs, delta=1):
        key = encode_subkey(subs)
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                row = self._con.execute(
                    "SELECT value FROM _globals WHERE ns=? AND subkey=?",
                    (ns, key)).fetchone()
                current = 0.0
                if row is not None and row[0] is not None:
                    parsed = json.loads(self._value_bytes(row[0]).decode())
                    current = float(parsed)
                value = current + float(delta)
                stored = int(value) if value.is_integer() else value
                self._con.execute(
                    "INSERT OR REPLACE INTO _globals (ns, subkey, value) "
                    "VALUES (?, ?, ?)",
                    (ns, key, json.dumps(stored).encode()))
                self._con.commit()
            except Exception:
                self._con.rollback()
                raise
        return stored

    def merge(self, dst_ns, dst_subs, src_ns, src_subs):
        src, dst = encode_subkey(src_subs), encode_subkey(dst_subs)
        with self._lock:
            rows = self._con.execute(
                "SELECT subkey, value FROM _globals WHERE ns=? AND "
                "(subkey=? OR (subkey>? AND subkey<?)) ORDER BY subkey",
                (src_ns, src, src, self._subtree_hi(src))).fetchall()
            rewritten = [(dst + bytes(k)[len(src):], v) for k, v in rows]
            self._con.executemany(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                [(dst_ns, k, v) for k, v in rewritten])
            self._con.commit()
        return len(rewritten)

    def count(self, ns):
        with self._lock:
            return self._con.execute(
                "SELECT COUNT(*) FROM _globals WHERE ns=?", (ns,)
            ).fetchone()[0]

    def flush(self):
        with self._lock:
            self._con.commit()
            self._con.execute("PRAGMA wal_checkpoint(FULL)")


class LmdbPDB:
    """Implementación LMDB (py-lmdb) del mismo contrato mínimo.

    Comparte EL MISMO store que el motor M (``mvm-nas -p X.lmdb``): mismas
    claves y mismos bytes (variante canónica del motor + fallback de lectura
    a la variante python/qpdb — ver pdb-development: subkey-encodings §5).
    Virtudes multi-proceso (la razón de ser): lecturas SIEMPRE frescas (mmap,
    SIN precarga), los commits de cualquier proceso son visibles al instante,
    escrituras serializadas por LMDB (breves). Caché de hijos por txn-id de
    LMDB: las cadenas $O no re-escanean el padre en cada paso.
    """

    name = "lmdb"
    _CACHE_MAX = 48

    def __init__(self, path, map_size_mb=None):
        import lmdb  # import perezoso: solo si se elige este motor

        self.path = str(path)
        mb = map_size_mb or int(os.environ.get(
            "PDB_LMDB_MAPSIZE_MB",
            os.environ.get("LUMEN_LMDB_MAPSIZE_MB", "1024")))
        self._env = lmdb.open(
            self.path, map_size=int(mb) * 1024 * 1024, max_dbs=4,
            subdir=True, lock=True, create=True)
        self._db = self._env.open_db(b"globals")
        self._lock = threading.RLock()
        self._children_cache = {}

    def close(self):
        if self._env is not None:
            self._env.close()
            self._env = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    # ── claves: dos convenciones conviven (censo 22-sep-2026) ──
    # 1) DOMINANTE (writer python/qpdb): bytes EXACTOS de encode_subkey —
    #    números sortables (flip), 0xFF por sub, SIN FF final.
    # 2) MOTOR (writer rust/MVM): números IEEE CRUDOS (3FF0 = +1.0, medido en
    #    filas ^PERSONALITY del motor), sin FF por número, + 0xFF final.
    @staticmethod
    def _prefix(ns: str) -> bytes:
        return ns.encode() + b"\x00"

    @classmethod
    def _primary_key(cls, ns, subs) -> bytes:
        """Variante dominante: mismas bytes que pdb_tools.encode_subkey."""
        return cls._prefix(ns) + encode_subkey(subs)

    @classmethod
    def _engine_key(cls, ns, subs) -> bytes:
        """Variante del motor rust: números crudos + terminador final."""
        k = bytearray(cls._prefix(ns))
        for s in subs:
            if isinstance(s, (int, float)) and not isinstance(s, bool):
                k += b"\x01" + struct.pack(">d", float(s))
            else:
                k += encode_subkey([s])
        k += b"\xff"
        return bytes(k)

    @classmethod
    def _engine_prefix(cls, ns, subs) -> bytes:
        """Prefijo de la variante motor (sin el 0xFF final)."""
        return cls._engine_key(ns, subs)[:-1]

    @classmethod
    def _subtree_window(cls, ns, subs):
        """Ventana [min(P1,P2), max(P1,P2)+0xFFFF] que cubre AMBAS variantes."""
        p1 = cls._primary_key(ns, subs)
        p2 = cls._engine_key(ns, subs)
        lo, hi = (p1, p2) if p1 <= p2 else (p2, p1)
        return lo, hi + b"\xff\xff"

    @staticmethod
    def _sub_eq(a, b) -> bool:
        return a == b  # 1 == 1.0; str == str

    @staticmethod
    def _sub_cmp(a, b) -> int:
        an = isinstance(a, (int, float)) and not isinstance(a, bool)
        bn = isinstance(b, (int, float)) and not isinstance(b, bool)
        if an and bn:
            return (a > b) - (a < b)
        if an:
            return -1  # números < strings (orden canónico M)
        if bn:
            return 1
        return (a > b) - (a < b)

    @classmethod
    def _decoded(cls, key: bytes):
        z = key.find(b"\x00")
        if z == -1:
            return None
        try:
            return decode_subkey(key[z + 1:])
        except Exception:
            return None

    @classmethod
    def _matches(cls, decoded, subs) -> bool:
        return (decoded is not None and len(decoded) >= len(subs)
                and all(cls._sub_eq(a, b) for a, b in zip(decoded, subs)))

    # ── operaciones núcleo ──
    def set(self, ns, subs, value):
        key = self._primary_key(ns, subs)
        other = self._engine_key(ns, subs)
        raw = json.dumps(value, ensure_ascii=False).encode()
        with self._lock, self._env.begin(write=True, db=self._db) as txn:
            txn.put(key, raw)
            if other != key and txn.get(other) is not None:
                txn.put(other, raw)  # gemela del motor existente → sincronizar
        return True

    def set_raw(self, ns, pairs):
        """Bulk raw: [(subkey_bytes verbatim, value_bytes)] en UNA transacción."""
        pairs = list(pairs)
        base = self._prefix(ns)
        with self._lock, self._env.begin(write=True, db=self._db) as txn:
            for k, v in pairs:
                txn.put(base + bytes(k), b"" if v is None else bytes(v))
        return len(pairs)

    def get_raw(self, ns, subkey):
        with self._env.begin(db=self._db) as txn:
            return txn.get(self._prefix(ns) + bytes(subkey))

    def get(self, ns, subs, default=None):
        k1 = self._primary_key(ns, subs)
        k2 = self._engine_key(ns, subs)
        with self._env.begin(db=self._db) as txn:
            raw = txn.get(k1)
            if raw is None and k2 != k1:
                raw = txn.get(k2)
        if raw is None or raw == b"":
            return default  # b"" = sentinel de nodo estructural (NULL migrado)
        try:
            return json.loads(raw.decode())
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return raw.decode(errors="replace")

    def _children(self, ns, parent_subs):
        pk = self._prefix(ns) + encode_subkey(parent_subs)
        with self._lock:
            with self._env.begin(db=self._db) as txn:
                tid = txn.id()
                ent = self._children_cache.get(pk)
                if ent is not None and ent[0] == tid:
                    return ent[1]
                lo, hi = self._subtree_window(ns, parent_subs)
                nlev = len(parent_subs)
                seen = {}
                cur = txn.cursor()
                ok = cur.set_range(lo)
                while ok:
                    k = cur.key()
                    if k > hi:
                        break
                    dec = self._decoded(k)
                    if self._matches(dec, parent_subs) and len(dec) > nlev:
                        c = dec[nlev]
                        seen[(0, float(c)) if isinstance(c, (int, float))
                             else (1, c)] = c
                    ok = cur.next()
                nums = sorted(v for k, v in seen.items() if k[0] == 0)
                strs = sorted(v for k, v in seen.items() if k[0] == 1)
                children = nums + strs
                if len(self._children_cache) >= self._CACHE_MAX:
                    self._children_cache.pop(next(iter(self._children_cache)))
                self._children_cache[pk] = (tid, children)
                return children

    def order(self, ns, subs, direction=1):
        """$ORDER: subs = padre + posición actual ('' = desde el borde)."""
        if not subs:
            raise ValueError("$ORDER necesita al menos un subscript")
        parent_subs, current = list(subs[:-1]), subs[-1]
        children = self._children(ns, parent_subs)
        if not children:
            return None
        if current in ("", None):
            return children[0] if direction >= 0 else children[-1]
        for i, c in enumerate(children):
            if self._sub_eq(c, current):
                if direction >= 0:
                    return children[i + 1] if i + 1 < len(children) else None
                return children[i - 1] if i >= 1 else None
        # current no listado (nodo borrado): primer candidato "más allá"
        if direction >= 0:
            for c in children:
                if self._sub_cmp(c, current) > 0:
                    return c
            return None
        prev = None
        for c in children:
            if self._sub_cmp(c, current) < 0:
                prev = c
            else:
                break
        return prev

    def data(self, ns, subs):
        k1 = self._primary_key(ns, subs)
        k2 = self._engine_key(ns, subs)
        with self._env.begin(db=self._db) as txn:
            raw = txn.get(k1)
            if raw is None and k2 != k1:
                raw = txn.get(k2)
            own = raw is not None and raw != b""
            # hijo por BYTE: prefijo dominante o prefijo motor (inmune al
            # baile de signos raw/sortable del decode; los FF terminadores
            # de cada nivel hacen el prefijo seguro frente a hermanos)
            child = False
            p1 = k1
            p2 = self._engine_prefix(ns, subs)
            lo, hi = self._subtree_window(ns, subs)
            cur = txn.cursor()
            ok = cur.set_range(lo)
            while ok:
                k = cur.key()
                if k > hi:
                    break
                if k != k1 and k != k2 and (k.startswith(p1) or k.startswith(p2)):
                    child = True
                    break
                ok = cur.next()
        return 11 if own and child else 1 if own else 10 if child else 0

    def kill(self, ns, subs):
        # matching por BYTE (prefijo dominante o prefijo motor): cubre el nodo
        # y todo su subárbol en AMBAS convenciones sin depender del decode
        p1 = self._primary_key(ns, subs)
        p2 = self._engine_prefix(ns, subs)
        lo, hi = self._subtree_window(ns, subs)
        keys = []
        with self._env.begin(db=self._db) as txn:
            cur = txn.cursor()
            ok = cur.set_range(lo)
            while ok:
                k = cur.key()
                if k > hi:
                    break
                if k.startswith(p1) or k.startswith(p2):
                    keys.append(bytes(k))
                ok = cur.next()
        if not keys:
            return 0
        with self._lock, self._env.begin(write=True, db=self._db) as txn:
            for k in keys:
                txn.delete(k)
        return len(keys)

    def merge(self, dst_ns, dst_subs, src_ns, src_subs):
        lo, hi = self._subtree_window(src_ns, src_subs)
        rows = []
        with self._env.begin(db=self._db) as txn:
            cur = txn.cursor()
            ok = cur.set_range(lo)
            while ok:
                k = cur.key()
                if k > hi:
                    break
                dec = self._decoded(k)
                if self._matches(dec, src_subs):
                    rows.append((dec, bytes(cur.value())))
                ok = cur.next()
        n = 0
        with self._lock, self._env.begin(write=True, db=self._db) as txn:
            for dec, val in rows:
                new_subs = list(dst_subs) + dec[len(src_subs):]
                txn.put(self._primary_key(dst_ns, new_subs), val)
                n += 1
        return n

    def count(self, ns):
        base = self._prefix(ns)
        n = 0
        with self._env.begin(db=self._db) as txn:
            cur = txn.cursor()
            ok = cur.set_range(base)
            while ok:
                if not cur.key().startswith(base):
                    break
                n += 1
                ok = cur.next()
        return n

    def incr(self, ns, subs, delta=1):
        k1 = self._primary_key(ns, subs)
        k2 = self._engine_key(ns, subs)
        with self._lock, self._env.begin(write=True, db=self._db) as txn:
            raw = txn.get(k1)
            if raw is None and k2 != k1:
                raw = txn.get(k2)
            current = 0.0
            if raw not in (None, b""):
                try:
                    current = float(json.loads(raw.decode()))
                except (ValueError, TypeError):
                    current = 0.0
            value = current + float(delta)
            stored = int(value) if float(value).is_integer() else value
            enc = json.dumps(stored).encode()
            txn.put(k1, enc)
            if k2 != k1 and txn.get(k2) is not None:
                txn.put(k2, enc)  # gemela legacy → sincronizar
        return stored

    def flush(self):
        if self._env is not None:
            try:
                self._env.sync(True)  # force (firma posicional según versión)
            except TypeError:
                self._env.sync()


def connect(path=None, engine=None):
    """Selección de motor con fallback automático (flag PDB_ENGINE)."""
    engine = (engine or os.environ.get("PDB_ENGINE", "sqlite")).lower()
    if engine not in ("sqlite", "redb", "lmdb"):
        raise ValueError("PDB_ENGINE debe ser 'sqlite', 'redb' o 'lmdb'")
    if engine == "redb":
        redb_path = path or os.environ.get("PDB_REDB_PATH") or str(
            Path(os.environ.get("PDB_PATH", _HERE / "lumen-pdb.db")).with_suffix(".redb"))
        try:
            return RedbPDB(redb_path)
        except (OSError, AttributeError) as e:
            print(f"[lumen_pdb] redb no disponible ({e}) — fallback a sqlite",
                  file=sys.stderr)
    if engine == "lmdb":
        lmdb_path = path or os.environ.get("PDB_LMDB_PATH") or str(
            Path(os.environ.get("PDB_PATH", _HERE / "lumen-pdb.db")).with_suffix(".lmdb"))
        try:
            return LmdbPDB(lmdb_path)
        except Exception as e:
            print(f"[lumen_pdb] lmdb no disponible ({e}) — fallback a sqlite",
                  file=sys.stderr)
    return SqlitePDB(path)
