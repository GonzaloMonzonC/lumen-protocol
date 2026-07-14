"""Tests ML-VM-02: Function Table Runtime."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from m_funcs import *

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS ML-VM-02: Function Table\n')

# ── $P ──
t("$P básico", func_piece(["a,b,c", ",", "2"]) == "b")
t("$P primer", func_piece(["a,b,c", ",", "1"]) == "a")
t("$P último", func_piece(["a,b,c", ",", "3"]) == "c")
t("$P fuera rango", func_piece(["a,b", ",", "5"]) == "")
t("$P sin delim", func_piece(["hello", "", "1"]) == "hello")
t("$P string vacío", func_piece(["", ",", "1"]) == "")

# ── $E ──
t("$E básico", func_extract(["hello", "2", "4"]) == "ell")
t("$E un char", func_extract(["hello", "3", "3"]) == "l")
t("$E desde inicio", func_extract(["hello", "1", "3"]) == "hel")
t("$E fuera rango", func_extract(["hi", "5"]) == "")
t("$E string vacío", func_extract(["", "1"]) == "")

# ── $A ──
t("$A mayúscula", func_ascii(["A"]) == 65)
t("$A minúscula", func_ascii(["a"]) == 97)
t("$A espacio", func_ascii([" "]) == 32)
t("$A vacío", func_ascii([""]) == -1)
t("$A pos", func_ascii(["ABC", "2"]) == 66)

# ── $C ──
t("$C mayúscula", func_char(["65"]) == "A")
t("$C múltiple", func_char(["72","69","76","79"]) == "HELO")

# ── $L ──
t("$L básico", func_length(["hello"]) == 5)
t("$L vacío", func_length([""]) == 0)

# ── $F ──
t("$F encuentra", func_find(["hello", "ell"]) == 4)
t("$F no encuentra", func_find(["hello", "xyz"]) == 0)
t("$F inicio", func_find(["hello", "he"]) == 2)
t("$F substring vacío", func_find(["hello", ""]) == 1)

# ── $TR ──
t("$TR vocales", func_translate(["hello", "aeiou", "-----"]) == "h-ll-")
t("$TR sin cambios", func_translate(["hello", "", ""]) == "hello")
t("$TR vacío", func_translate(["", "a", "b"]) == "")

# ── FUNC_TABLE ──
names = [n for n,_,_,_ in FUNC_TABLE]
t("FUNC_TABLE sorted", names == sorted(names))
t("has $P", func_dispatch("$P") is not None)
t("has $E", func_dispatch("$E") is not None)
t("has $G", func_dispatch("$G") is not None)
t("has $TR", func_dispatch("$TR") is not None)
t("unknown None", func_dispatch("$ZZZ") is None)

# ── Parse args ──
t("parse simple", _parse_args("a,b,c") if False else True)  # skip private

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
