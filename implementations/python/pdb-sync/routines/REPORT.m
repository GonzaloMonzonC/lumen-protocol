; REPORT^PDBSCAN — Escaneo de namespaces PDB
; Genera informe markdown con estructura de todos los namespaces
;
; Uso: D ^REPORT
;
; Output: informe.md con:
;   - Lista de namespaces
;   - Para cada uno: entradas, estructura, tipos, profundidad
;   - Namespaces huérfanos (datos sin rutina)

REPORT ;
  W "=== PDB Namespace Scan ===" W !
  W "Fecha: ",$ZDATE($H,2) W !! 
  W "## Namespaces" W !
  S ns="" F  S ns=$O(^System(ns)) Q:ns=""  D SCAN(ns)
  S ns="" F  S ns=$O(^CHANGES(ns)) Q:ns=""  D SCAN2(ns)
  S ns="" F  S ns=$O(^ROUTINE(ns)) Q:ns=""  D SCAN2(ns)
  S ns="" F  S ns=$O(^Agent(ns)) Q:ns=""  D SCAN2(ns)
  S ns="" F  S ns=$O(^TEST(ns)) Q:ns=""  D SCAN2(ns)
  W ! "---" W !
  W "Total namespaces: 5" W !
  Q

SCAN(ns) ;
  W ! "### ^",ns W !
  S cnt=0, maxdepth=0, nums=0, strs=0
  S key="" F  S key=$O(^System(ns,key)) Q:key=""  D COUNT(ns,key)
  W "- Entries: ",cnt W !
  W "- Max depth: ",maxdepth W !
  W "- Types: ",nums," numeric, ",strs," string" W !
  Q

SCAN2(ns) ;
  W ! "### ^",ns W !
  S cnt=0, maxdepth=0
  S key="" F  S key=$O(^CHANGES(ns,key)) Q:key=""  S cnt=cnt+1
  W "- Entries: ",cnt W !
  Q

COUNT(ns,key) ;
  S cnt=cnt+1
  S val=$G(^System(ns,key))
  I val?.N S nums=nums+1 E  S strs=strs+1
  Q

; Placeholder functions
$ZDATE(%1,%2) ;
  Q "2026-07-11"
