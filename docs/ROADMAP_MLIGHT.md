# M-Light Roadmap — MSM Compatibility Plan

## OBJ-1: String Functions ($L, $F, $TR)
`$L(string)` → LENGTH · `$F(string,sub)` → FIND · `$TR(string,old,new)` → TRANSLATE
Cubre ~15% del código MSM STU. Fácil.

## OBJ-2: Variable Operations
KILL de locales · SET múltiple con coma (`S A=1,B=2`) · NEW (push/pop scope)
Cubre ~10% del código MSM.

## OBJ-3: Numeric Operations
`+expr` casting · `#FF` hex literales · `\` división entera · `**` exponente
Cubre ~10% del código MSM.

## OBJ-4: Control Flow
`G label` (GOTO) · `D label` (DO) · `$ZT` error trap · `$ECODE` / `$ZERROR`
Cubre ~15% del código MSM.

## OBJ-5: I/O Operations
`W *n` (ASCII) · `?n` (column) · `R prompt:var` (READ) · `O`/`U`/`C` device
Cubre ~10% del código MSM.

## OBJ-6: MSM Compatibility Complete
Integración full: sandbox 40+ tests, REPL, D^ROUTINE, docs.
