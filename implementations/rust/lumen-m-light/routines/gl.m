%GL ; Global Lister — sin D, sin Q final
 N ns,siz,tot
 W !,"=== ^GLOBALes ===",!
 S tot=0,ns=""
GL1 S ns=$O(^GLOBAL_SIZES(ns))
 G:ns="" GL2
 S siz=$G(^GLOBAL_SIZES(ns),0)
 S tot=tot+siz
 W !,"  ^",ns,": ",siz
 G GL1
GL2 W !,"Total: ",tot,!
