"""Tests MREPL v10: Char-by-char debug + 22 MSMSHELL features."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from mrepl import MREPL

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MREPL v10 — 22 tests\n')

r=MREPL(); r2=MREPL(debug=True); r3=MREPL(context="System")

# Prompts
t("> prompt", r.prompt=="> ")
t("DEBUG prompt","DEBUG" in r2.prompt)
t("[ctx] prompt","System" in r3.prompt)
r.exec("toggle")
t("D> prompt", r.prompt.startswith("D"))
r.exec("toggle")

# Commands
t("empty", r.exec("")=="")
t("exit", r.exec("exit")=="")

# $ZREF + Alias
r.exec("$O(^TEST(\"\"))")
t("zref", r.last_zref is not None)
t("alias o", r.exec("o TEST(\"\")") is not None)

# History pages
r.exec("S a=1"); r.exec("S b=2")
t("+ page up", isinstance(r.exec("+"),str))
t("- page down", isinstance(r.exec("-"),str))

# Help
t("? help","?" in r.exec("?"))
t("?? last10", isinstance(r.exec("??"),str))
t("?$O","$O" in r.exec("?$O"))
t("?USE help", isinstance(r.exec("?USE"),str))

# Debug
t("debug on","char" in r.exec("debug"))
t("debug off","OFF" in r.exec("debug"))

# Recall
r.exec("S x=99")
t("! recall", r.exec("!") is not None)

# NOMEM
t("nomem", "NOMEM" in r.exec("nomem"))
r.exec("safe")

# use
t("use context","CHANGES" in r.exec("use CHANGES"))

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
