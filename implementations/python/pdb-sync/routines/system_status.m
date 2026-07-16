%SS ; System Status — ported from MSM %SS to LUMEN/PDB
 ; Original: Micronetics Design Corp @1988
 ; Ported: Hermes + Cadences Lab, 2026-07-16
 ;
 ; Shows: active jobs, ^GLOBAL sizes, PDB stats, agent health
 ;
 N jobs,pid,status,gas,io,nssize,ns,n
 ;
 ;-- Header --
 W !,"=== LUMEN System Status ===",!
 W !,"Engine: ",$G(^CONFIG("engine"),"python"),!
 ;
 ;-- Active Jobs (MVM processes) --
 W !,"--- Active Jobs ---",!
 S pid="" F  S pid=$O(^STATE(pid)) Q:pid=""  D
 . S status=$G(^STATE(pid,"status"),"unknown")
 . S gas=$G(^STATE(pid,"gas"),0)
 . S io=$G(^STATE(pid,"io_device"),0)
 . W !,?2,pid,?12,status,?22,"gas=",gas,?32,"io=",io
 ;
 ;-- ^GLOBAL Sizes --
 W !!,!,"--- ^GLOBAL Sizes ---",!
 S ns="" F  S ns=$O(^GLOBAL_SIZES(ns)) Q:ns=""  D
 . S n=$G(^GLOBAL_SIZES(ns),0)
 . W !,?2,ns,?30,$J(n,8)," entries"
 ;
 ;-- Agent Heartbeats --
 W !!,!,"--- Agents ---",!
 S pid="" F  S pid=$O(^HEARTBEAT(pid)) Q:pid=""  D
 . S status=$P($G(^(pid)),"|",2)
 . S color=$S(status="alive":"🟢",status="degraded":"🟡",1:"🔴")
 . W !,?2,color," ",pid,?22,status
 ;
 ;-- PDB Connection --
 W !!,!,"--- PDB ---",!
 W !,?2,"Engine: ",$G(^CONFIG("pdb_engine"),"sqlite"),!
 W !,?2,"Path: ",$G(^CONFIG("pdb_path"),"default"),!
 ;
 Q
