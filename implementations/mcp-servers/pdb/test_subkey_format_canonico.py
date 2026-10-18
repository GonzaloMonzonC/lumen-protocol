#!/usr/bin/env python3
"""test_subkey_format_canonico.py — L-02 / L-07 (Opcion D)

El defecto: dos convenciones incompatibles para los 8 bytes de un f64 en un
subkey numerico. El motor Rust escribe CRUDO (3FF0 = 1.0), el MCP escribia
SORTABLE (BFF0 = 1.0). Cada lado se leia a si mismo bien; al cruzar, 1.0 se
convertia en -3.9999... y 0.0 en nan, y pdb_get devolvia found:false sobre
datos que existian. Todo en silencio.

Opcion D: el byte de tipo es el discriminante.
    0x01 = crudo (motor Rust, y lo que hay en produccion)
    0x03 = sortable
    0x01 + digitos ASCII + 0xFF = legacy (se sigue leyendo)

Sin dependencias externas.
    python test_subkey_format_canonico.py [-v]
"""
import os
import struct
import sys
import tempfile
from pathlib import Path


def find_pdb():
    for parent in Path(__file__).resolve().parents:
        cand = parent / "implementations/mcp-servers/pdb"
        if (cand / "pdb_tools.py").is_file():
            return cand
    return Path.home() / "Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"


def load(pdbdir):
    sys.path.insert(0, str(pdbdir))
    os.environ.setdefault("PDB_PATH", tempfile.mktemp(suffix=".db"))
    import pdb_tools
    return pdb_tools


def main():
    verbose = "-v" in sys.argv
    pdbdir = find_pdb()
    if not (pdbdir / "pdb_tools.py").is_file():
        print(f"SKIP: no encuentro {pdbdir}/pdb_tools.py")
        return 0

    t = load(pdbdir)
    fails = []

    def chk(cond, msg):
        if not cond:
            fails.append(msg)

    # ── 1. el discriminante existe y es estable ──
    chk(t.SUBKEY_NUMERIC_RAW == 0x01, "SUBKEY_NUMERIC_RAW deberia ser 0x01")
    chk(t.SUBKEY_NUMERIC_SORTABLE == 0x03, "SUBKEY_NUMERIC_SORTABLE deberia ser 0x03")
    print(f"discriminantes: raw=0x{t.SUBKEY_NUMERIC_RAW:02x} "
          f"sortable=0x{t.SUBKEY_NUMERIC_SORTABLE:02x}")

    # ── 2. round-trip en AMBOS formatos, incluidos negativos y cero ──
    valores = [0, 1, -1, 2, 10, -10, 0.5, -0.5, 383, 1e-9, 123456.789]
    for fmt in ("raw", "sortable"):
        for v in valores:
            blob = t._encode_numeric(v, fmt)
            typ = blob[0]
            esperado_typ = 0x01 if fmt == "raw" else 0x03
            chk(typ == esperado_typ, f"{fmt}: byte de tipo 0x{typ:02x} != 0x{esperado_typ:02x}")
            leido = t._decode_numeric(typ, blob[1:9])
            chk(abs(leido - v) < 1e-9,
                f"{fmt}: round-trip de {v} dio {leido}")
        print(f"  round-trip {fmt:8s}: OK ({len(valores)} valores)")

    # ── 3. EL BUG: los bytes CRUDOS del motor ya NO se leen como sortables ──
    #     El motor escribe f64::to_be_bytes(1.0) = 3FF0000000000000
    motor_1 = b'\x01' + struct.pack('>d', 1.0) + b'\xff'
    leido = t.decode_subkey(motor_1)
    chk(leido == [1], f"L-07: los bytes crudos del motor dan {leido}, esperado [1]")
    if verbose:
        print(f"  motor ^X(1) = {motor_1.hex()} -> {leido}")

    motor_0 = b'\x01' + struct.pack('>d', 0.0) + b'\xff'
    leido0 = t.decode_subkey(motor_0)
    chk(leido0 == [0], f"L-02: 0.0 crudo da {leido0}, esperado [0] (antes: nan)")
    if verbose:
        print(f"  motor ^X(0) = {motor_0.hex()} -> {leido0}")

    motor_neg = b'\x01' + struct.pack('>d', -1.0) + b'\xff'
    chk(t.decode_subkey(motor_neg) == [-1],
        f"-1.0 crudo da {t.decode_subkey(motor_neg)}, esperado [-1]")

    # ── 4. el pull ya no deforma los subs numericos ──
    #     Caso del informe: ^TSUB(0),(1),(2),(10) escritos por el motor
    def motor_key(n):
        return b'\x01' + struct.pack('>d', float(n)) + b'\xff'

    obtenido = sorted(t.decode_subkey(motor_key(n))[0] for n in (0, 1, 2, 10))
    chk(obtenido == [0, 1, 2, 10],
        f"L-02: pull devuelve {obtenido}, esperado [0, 1, 2, 10]")
    print(f"  pull numericos : {obtenido}")

    # ── 5. nodo con valor Y hijos: el hijo numerico se conserva ──
    #     ^TSUB("a")="letra" con ^TSUB("a",1)="anidado"
    anidado = b'\x02a\xff' + b'\x01' + struct.pack('>d', 1.0) + b'\xff'
    subs = t.decode_subkey(anidado)
    chk(subs == ["a", 1], f"'a',1 da {subs}, esperado ['a', 1]")
    if verbose:
        print(f"  anidado {anidado.hex()} -> {subs}")

    # ── 6. legacy ASCII se sigue leyendo ──
    legacy = b'\x01' + b'42' + b'\xff'
    chk(t.decode_subkey(legacy) == [42], f"legacy ASCII da {t.decode_subkey(legacy)}")
    print(f"  legacy ASCII   : {t.decode_subkey(legacy)}")

    # ── 7. el encoder por defecto escribe lo que el MOTOR puede leer ──
    chk(t._numeric_format() == "raw",
        f"formato por defecto {t._numeric_format()!r}, esperado 'raw' (lo que lee el motor)")
    blob_def = t.encode_subkey([1])
    chk(blob_def[:1] == b'\x01',
        f"encode_subkey([1]) emite tipo 0x{blob_def[0]:02x}, esperado 0x01 (crudo)")
    # y que el motor lo lea: los 8 bytes son f64 crudo exacto
    payload = blob_def[1:9]
    chk(struct.unpack('>d', payload)[0] == 1.0,
        f"los 8 bytes no son f64 crudo de 1.0: {payload.hex()}")
    print(f"  encode por def : {blob_def.hex()} (crudo)")

    # ── 8. env cambia el formato de escritura pero NO la lectura ──
    os.environ["SUBKEY_NUMERIC_FORMAT"] = "sortable"
    try:
        chk(t._numeric_format() == "sortable", "SUBKEY_NUMERIC_FORMAT=sortable no se respeta")
        b_sort = t.encode_subkey([1])
        chk(b_sort[:1] == b'\x03', f"con sortable el tipo es 0x{b_sort[0]:02x}, esperado 0x03")
        # y se sigue leyendo bien
        chk(t.decode_subkey(b_sort) == [1], f"round-trip sortable por encode_subkey: "
                                            f"{t.decode_subkey(b_sort)}")
        # y los crudos viejos siguen leyendose aunque el default sea sortable
        chk(t.decode_subkey(motor_1) == [1], "con default sortable se rompe la lectura de crudos")
        print(f"  env sortable   : {b_sort.hex()} + lectura de crudos OK")
    finally:
        os.environ.pop("SUBKEY_NUMERIC_FORMAT", None)

    # ── 9. orden por memcmp: dentro de 0x03 los negativos ordenan bien ──
    neg = [t._encode_numeric(v, "sortable") for v in (-10, -1, 0, 1, 10)]
    ordenados = sorted(neg)
    decodificados = [t._decode_numeric(b[0], b[1:9]) for b in ordenados]
    chk(decodificados == [-10, -1, 0, 1, 10],
        f"memcmp en 0x03 no ordena: {decodificados}")
    print(f"  orden memcmp   : {decodificados}")

    # ── 10. multinivel: numerico + string mezclados ──
    mix = t.encode_subkey(["ns", 5, "key"])
    chk(t.decode_subkey(mix) == ["ns", 5, "key"],
        f"multinivel mixto: {t.decode_subkey(mix)}")
    print(f"  multinivel     : {t.decode_subkey(mix)}")

    print()
    if fails:
        print(f"FALLO ({len(fails)})")
        for f in fails:
            print(f"   - {f}")
        return 1
    print("PASS: formato canonico con discriminante (L-02/L-07)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
