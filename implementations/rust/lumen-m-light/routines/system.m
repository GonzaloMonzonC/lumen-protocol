%SS ; System Status — M puro para WASM/PDB (v5 final)
 ; Funciona en WASM. Usa GOTO para bucles.
 ;
 N jobs,pid,st,gas
 W !,"=== LUMEN System Status ===",!
 ;
 ;-- Jobs --
 S jobs=0,pid=""
SSJOB S pid=$O(^STATE(pid)) G:pid="" SSJEND
 S jobs=jobs+1
 S st=$G(^STATE(pid,"status"),"?")
 S gas=$G(^STATE(pid,"gas"),0)
 W !,pid," ",st," gas=",gas
 G SSJOB
SSJEND W !,"Total jobs: ",jobs,!
 ;
 ;-- Agents --
 W !,"--- Agents ---",!
 S pid=""
SSAGT S pid=$O(^HEARTBEAT(pid)) G:pid="" SSEND
 S st=$P($G(^HEARTBEAT(pid)),"|",2)
 W !,"  ",pid," = ",st
 G SSAGT
 ;
 ;-- PDB --
 W !,!,"--- PDB ---"
 W !,"Engine: ",$G(^CONFIG("pdb_engine"),"sqlite")
 W !,"Path: ",$G(^CONFIG("pdb_path"),"?")
 ;
SSEND Q
