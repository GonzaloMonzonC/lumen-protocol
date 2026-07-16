%SS ; System Status — M puro para WASM/PDB
 ; Muestra: jobs activos, ^GLOBAL sizes, agents, PDB stats
 ; Compatible con M-Light (sin $V, sin $ZB, sin $ZMSM)
 ;
 N jobs,pid,status,gas,io,nssize,ns,n
 ;
 W !,"=== LUMEN System Status ===",!
 ;
 ;-- Active Jobs (MVM) --
 W !,"--- Jobs Activos ---",!
 S jobs=0
 S pid="" F  S pid=$O(^STATE(pid)) Q:pid=""  D
 . S jobs=jobs+1
 . S status=$G(^STATE(pid,"status"),"?")
 . S gas=$G(^STATE(pid,"gas"),0)
 . W !,?2,pid,?10,status,?20,"gas=",gas
 W !,?2,"Total: ",jobs,!
 ;
 ;-- ^GLOBAL Sizes --
 W !,"--- ^GLOBALes ---",!
 S ns="" F  S ns=$O(^GLOBAL_SIZES(ns)) Q:ns=""  D
 . S n=$G(^(ns),0)
 . W !,?2,ns,?25,$J(n,8)
 ;
 ;-- Agents --
 W !,"--- Agents ---",!
 S pid="" F  S pid=$O(^HEARTBEAT(pid)) Q:pid=""  D
 . S st=$P($G(^(pid)),"|",2)
 . S emoji=$S(st="alive":"+",st="degraded":"~",1:"-")
 . W !,?2,emoji," ",pid,?22,st
 ;
 ;-- PDB --
 W !,"--- PDB ---",!
 W !,?2,$G(^CONFIG("pdb_engine"),"sqlite"),!
 W !,?2,$G(^CONFIG("pdb_path"),"lumen.db"),!
 Q

%YD ; Date utility — M puro
 ; Returns current date in various formats
 ; %YD("D") = DD/MM/YYYY  %YD("H") = $HOROLOG
 N fmt,d,t
 S fmt=$G(%1,"D")
 S d=$G(^SYSTEM("date"),"2026-07-16")
 I fmt="H" W $P($H,",",1) Q
 I fmt="AA" W $E(d,3,4) Q
 W d Q

%WH ; Who — M puro
 ; Shows current sessions / connected devices
 N pid,dev,ip
 W !,"--- Sessions ---",!
 S pid="" F  S pid=$O(^SESSIONS(pid)) Q:pid=""  D
 . S dev=$P($G(^(pid)),"|",1)
 . S ip=$P($G(^(pid)),"|",2)
 . W !,?2,pid,?10,dev,?25,ip
 Q
