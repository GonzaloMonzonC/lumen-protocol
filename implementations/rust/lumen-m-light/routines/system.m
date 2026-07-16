%GL ; Global Lister — M puro para WASM/PDB
 ; Lista todos los ^GLOBALes con su tamaño
 ; Original MSM: usaba $V() para leer tabla interna
 ; Portado: usa ^GLOBAL_SIZES
 ;
 N ns,size,total
 W !,"=== ^GLOBAL Lister ===",!
 S total=0,ns=""
GL01 S ns=$O(^GLOBAL_SIZES(ns)) G:ns="" GLEND
 S size=$G(^GLOBAL_SIZES(ns),0)
 S total=total+size
 W !,?2,"^",ns,?30,$J(size,8)
 G GL01
GLEND W !,?2,$J("---",30)
 W !,?2,"Total",?30,$J(total,8)
 Q

%GLF ; Global Lister FULL — con detalle de subnodos
 ; Muestra estructura jerárquica: ^NS → sub1 → sub2
 ;
 N ns,key,val
 W !,"=== ^GLOBAL Tree ===",!
 S ns="" F  S ns=$O(^GLOBAL_SIZES(ns)) Q:ns=""  D
 . W !,"^",ns," (",$G(^GLOBAL_SIZES(ns),0),")"
 . S key="" F  S key=$O(@("^"_ns_"("_$C(34)_key_$C(34)_")")) Q:key=""  D
 . . W !,"  ",key
 . . S val=$G(@("^"_ns_"("_$C(34)_key_$C(34)_")"))
 . . W " = ",val
 Q
