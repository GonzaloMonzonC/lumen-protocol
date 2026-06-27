# M-Light Roadmap — MSM Compatibility Plan

## ✅ OBJ-1: String Functions ($L, $F, $TR)
`$L(string)` → LENGTH · `$F(string,sub)` → FIND · `$TR(string,old,new)` → TRANSLATE

## ✅ OBJ-2: Variable Operations
KILL de locales · SET múltiple con coma (`S A=1,B=2`) · NEW (push/pop scope)

## ✅ OBJ-3: Numeric Operations
`+expr` casting · `#FF` hex literales · `\` división entera · `#` módulo

## ✅ OBJ-4: Control Flow
`G label` (GOTO) · `D label` (DO) con retorno · Labels multilínea · Call stack

## ✅ OBJ-5: I/O Operations
`W *n` (ASCII) · `?n` (column) · `R prompt:var` (READ) · `O`/`U`/`C` device · `N` (NEW)

## 🎯 OBJ-6: PDB Cognitive Benchmark Demo
Demo profesional: PDB + M-Light vs RAG tradicional.
KPIs: $ORDER speed vs ANN, jerárquico vs plano, M expressions vs chunks.

## Lo que soporta M-Light ahora
- $GET/G, $DATA/D, $ORDER/O, $PIECE/P, $EXTRACT/E, $SELECT/S
- $LENGTH/L, $FIND/F, $TRANSLATE/TR
- SET (simple, comma-sep, global)
- KILL (local y global)
- FOR (infinito y con rango)
- IF/ELSE con bloques {}
- QUIT con postconditional
- GOTO (G label), DO (D label) con call stack
- WRITE (W *n, W !, W ?n, W "text")
- READ (R prompt:var)
- NEW, OPEN, USE, CLOSE
- Abreviaturas M ($O, $G, $D, $P, $E, $S, $L, $F, $TR)
- Hex literales (#FF = 255)
- Aritmética left-to-right (\ div, # mod, *, /, +, -)
- +cast numérico
- Variables locales y globales ^ns(subs)
- Comentarios ; inline
- REPL multilínea (pdb_m_repl)
- MSM STU coverage: ~70% de sintaxis básica
