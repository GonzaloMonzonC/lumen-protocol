//! SPLIT-BRAIN — el bug de pérdida silenciosa, arreglado.
//!
//! ## El bug que se arregla
//!
//! Antes: dos escritores con la misma identidad de nodo producían hechos que
//! colisionaban, y **el segundo se descartaba en silencio**:
//!
//! ```text
//! hechos enviados:  6
//! hechos guardados: 3
//! DESCARTADOS EN SILENCIO: 3
//! ```
//!
//! Sin error, sin log, sin conflicto. El sistema decía que todo había ido bien.
//!
//! ## La regla nueva
//!
//! - **mismo hash**      → duplicado (idempotencia), se ignora sin más
//! - **hash distinto**   → CONFLICTO: las dos versiones se guardan
//!
//! Nunca se descarta. Rechazar era el bug.

use lumen_mlight::{Host, MemoryHost};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::replicacion::Hecho;

fn hecho_v2(nodo: &str, seq: u64, inst: &str, epoch: u64, valor: &str, prev: &str) -> Hecho {
    Hecho::v2(nodo, "gps", seq, inst, epoch, "gps", valor, prev, seq)
}

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

#[test]
fn dos_instancias_del_mismo_barco_ya_no_se_pierden() {
    println!();
    println!("==================================================================");
    println!("SPLIT-BRAIN — dos instancias del MISMO barco");
    println!("==================================================================");

    let mut host = MemoryHost::default();

    // Instancia 1 escribe 3 hechos.
    let mut prev1 = String::new();
    let mut msg1 = Vec::new();
    for i in 0..3u64 {
        let h = hecho_v2("BARCO-A", i, "inst-AAA", 0, &format!("lat=41.{i}"), &prev1);
        prev1 = h.hash();
        msg1.push(hechos_wire::mensaje_de_hecho(&h));
    }
    let r1 = hechos_wire::recibir_hechos(&mut host, &msg1, None);
    println!("[{}] instancia AAA escribe 3 hechos -> {} aceptados",
        marca(r1.aceptados == 3), r1.aceptados);

    // Instancia 2 (reinstalación o partición) escribe los MISMOS seq.
    let mut prev2 = String::new();
    let mut msg2 = Vec::new();
    for i in 0..3u64 {
        let h = hecho_v2("BARCO-A", i, "inst-BBB", 1, &format!("lat=99.{i}"), &prev2);
        prev2 = h.hash();
        msg2.push(hechos_wire::mensaje_de_hecho(&h));
    }
    let r2 = hechos_wire::recibir_hechos(&mut host, &msg2, None);

    println!("[{}] instancia BBB escribe los mismos seq -> {} aceptados, {} conflictos, {} descartes",
        marca(r2.aceptados == 3 && r2.rechazados == 0),
        r2.aceptados, r2.conflictos, r2.rechazados);

    // LO IMPORTANTE: los 6 hechos están.
    let rama_a = hechos_store::leer_serie_de_rama(&host, "BARCO-A", "gps", "inst-AAA");
    let rama_b = hechos_store::leer_serie_de_rama(&host, "BARCO-A", "gps", "inst-BBB");
    println!("[{}] las DOS ramas coexisten -> AAA={} hechos, BBB={} hechos",
        marca(rama_a.len() == 3 && rama_b.len() == 3), rama_a.len(), rama_b.len());
    assert_eq!(rama_a.len(), 3, "la rama AAA debe conservarse entera");
    assert_eq!(rama_b.len(), 3, "la rama BBB debe conservarse entera");

    // Y el conflicto está registrado con evidencia.
    println!("[{}] conflictos registrados con evidencia -> {}",
        marca(r2.conflictos == 3), r2.conflictos);
    assert_eq!(r2.conflictos, 3, "cada colisión debe registrarse");
    assert!(!r2.detalle_conflictos.is_empty());
    for c in &r2.detalle_conflictos {
        println!("      {}", c.resumen());
    }

    // Ninguna cadena se rompe: cada rama verifica por separado.
    let v_a = hechos_store::verificar_serie(&rama_a);
    let v_b = hechos_store::verificar_serie(&rama_b);
    println!("[{}] cada rama verifica su propia cadena -> AAA={:?} BBB={:?}",
        marca(v_a.is_ok() && v_b.is_ok()),
        v_a.as_ref().err(), v_b.as_ref().err());
    assert!(v_a.is_ok(), "rama AAA vulnerable: {v_a:?}");
    assert!(v_b.is_ok(), "rama BBB vulnerable: {v_b:?}");

    println!("==================================================================");
}

#[test]
fn reenviar_lo_mismo_es_duplicado_no_conflicto() {
    // Idempotencia: si un nodo reintenta, no debe generar conflictos falsos.
    let mut host = MemoryHost::default();
    let h = hecho_v2("BARCO-A", 0, "inst-AAA", 0, "lat=41.0", "");
    let m = hechos_wire::mensaje_de_hecho(&h);

    let r1 = hechos_wire::recibir_hechos(&mut host, std::slice::from_ref(&m), None);
    let r2 = hechos_wire::recibir_hechos(&mut host, std::slice::from_ref(&m), None);

    println!();
    println!("  primer envio: aceptados={} duplicados={}", r1.aceptados, r1.duplicados);
    println!("  reenvio:      aceptados={} duplicados={} conflictos={}",
        r2.aceptados, r2.duplicados, r2.conflictos);

    assert_eq!(r1.aceptados, 1);
    assert_eq!(r2.aceptados, 0);
    assert_eq!(r2.duplicados, 1, "el reenvio es duplicado, no conflicto");
    assert_eq!(r2.conflictos, 0, "un reenvio NO debe marcar conflicto");
    assert_eq!(r2.rechazados, 0, "un reenvio NO debe rechazarse");
}

#[test]
fn el_formato_v1_sigue_leyendose() {
    // Compatibilidad: los hechos escritos antes del cambio no se migran.
    let mut host = MemoryHost::default();
    let h = Hecho::v1("BARCO-VIEJO", "gps", 0, "gps", "lat=41.0", "", 1);
    hechos_store::guardar(&mut host, &h).expect("guardar v1");

    let leido = hechos_store::leer_principal(&host, "BARCO-VIEJO", "gps", 0)
        .expect("un hecho v1 debe seguir leyendose");
    println!();
    println!("  v1 leido: version={} valor={} instance='{}'",
        leido.version, leido.valor, leido.instance_id);
    assert_eq!(leido.version, 1);
    assert_eq!(leido.valor, "lat=41.0");
    assert_eq!(leido.instance_id, "", "un v1 no tiene instancia");
    assert_eq!(leido.epoch, 0);
}

#[test]
fn una_serie_v2_normal_no_genera_conflictos() {
    // El camino feliz: un barco, una instancia, sin split-brain.
    let mut host = MemoryHost::default();
    let mut prev = String::new();
    let mut msgs = Vec::new();
    for i in 0..10u64 {
        let h = hecho_v2("BARCO-A", i, "inst-AAA", 0, &format!("lat=41.{i}"), &prev);
        prev = h.hash();
        msgs.push(hechos_wire::mensaje_de_hecho(&h));
    }
    let r = hechos_wire::recibir_hechos(&mut host, &msgs, None);
    println!();
    println!("  serie normal: aceptados={} conflictos={} rechazados={}",
        r.aceptados, r.conflictos, r.rechazados);
    assert_eq!(r.aceptados, 10);
    assert_eq!(r.conflictos, 0, "sin split-brain no debe haber conflictos");
    assert_eq!(r.rechazados, 0);
}

#[test]
fn las_instancias_en_una_posicion_se_detectan() {
    let mut host = MemoryHost::default();
    hechos_store::guardar(&mut host, &hecho_v2("BARCO-A", 0, "inst-AAA", 0, "a", "")).unwrap();
    hechos_store::guardar(&mut host, &hecho_v2("BARCO-A", 0, "inst-BBB", 1, "b", "")).unwrap();

    let instancias = hechos_store::instancias_en_posicion(&host, "BARCO-A", "gps", 0);
    println!();
    println!("  instancias en (BARCO-A, gps, 0): {:?}", instancias);
    assert_eq!(instancias.len(), 2, "deben detectarse las dos ramas");
    assert!(instancias.contains(&"inst-AAA".to_string()));
    assert!(instancias.contains(&"inst-BBB".to_string()));
}
