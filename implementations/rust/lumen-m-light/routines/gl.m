%GL ; Global Lister — sin Q final
 N ns,siz,tot
 W !,"=== ^GLOBALes ===",!
 S tot=0,ns=""
GL1 S ns=$O(^GLOBAL_SIZES(ns))
 G:ns="" GL2
 S siz=$G(^GLOBAL_SIZES(ns),0)
 S tot=tot+siz
 W !,?2,ns,?30,$J(siz,8)
 G GL1
GL2 W !,?2,$J("---",30)
 W !,?2,"Total",?30,$J(tot,8)
 W !
 ; no Q — fin de rutina implicito
