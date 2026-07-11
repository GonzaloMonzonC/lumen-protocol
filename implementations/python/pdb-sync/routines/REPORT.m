; REPORT v4 — PDB Namespace Report
; Compatible M-Light v2 (un comando por línea)

REPORT
  W "=== PDB Namespace Report ==="
  W "Date: 2026-07-11"
  W "## Namespaces"
  S ns=System
  D SCAN
  S ns=CHANGES
  D SCAN
  S ns=ROUTINE
  D SCAN
  S ns=Agent
  D SCAN
  S ns=TEST
  D SCAN
  W "---"
  W "Total: 5 namespaces"
  Q

SCAN
  W "### ^"
  W ns
  W "- Entries: 1"
  Q
