//! Persistencia REAL de hechos en LMDB, con cierre y reapertura.
//!
//! Lo que el test en memoria no puede probar: que los hechos y las firmas
//! sobrevivan a cerrar el proceso. Si esto falla, un barco perdería su bitácora
//! al apagarse, que es justo lo que no puede pasar.

#![cfg(feature = "motor-lmdb")]

use lumen_mlight::{Host, MemoryHost};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::Hecho;

fn hecho(nodo: &str, seq: u64, valor: &str, prev: &str) -> Hecho {
    Hecho {
        nodo: nodo.into(),
        serie: "gps".into(),
        seq,
        clave: "gps".into(),
        valor: valor.into(),
        prev_hash: prev.into(),
        ts: seq,
        firma: None,
        ..Default::default()
    }
}

#[test]
fn los_hechos_y_las_firmas_sobreviven_al_reinicio() {
    let dir = std::env::temp_dir().join(format!("lumen-hechos-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let dir_s = dir.to_string_lossy().to_string();

    let id = Identidad::generar();
    let clave = id.clave_publica();
    let firmas_esperadas;

    // ── 1. Escribir 200 muestras firmadas por bloque de 100 y cerrar ──
    {
        let mut host = MemoryHost::from_lmdb(&dir_s).expect("abrir lmdb");
        let mut prev = String::new();
        let mut firmadas = 0;
        for i in 0..200u64 {
            let mut h = hecho("BARCO-A", i, &format!("lat=41.{i}"), &prev);
            // Firma solo cada 100 (perfil por_bloque)
            if (i + 1) % 100 == 0 {
                h.firmar(&id);
                firmadas += 1;
            }
            prev = h.hash();
            hechos_store::guardar(&mut host, &h).expect("guardar");
        }
        firmas_esperadas = firmadas;
        // LMDB es transaccional: cada set ya queda en disco.
        assert_eq!(firmas_esperadas, 2);
    } // host se cierra aqui

    // ── 2. Reabrir y comprobar que estan todos ──
    let host = MemoryHost::from_lmdb(&dir_s).expect("reabrir lmdb");
    let serie = hechos_store::leer_serie(&host, "BARCO-A", "gps");

    println!();
    println!("==================================================================");
    println!("PERSISTENCIA EN LMDB — cerrar y reabrir");
    println!("==================================================================");
    println!("[{}] hechos tras reabrir -> {} de 200",
        if serie.len() == 200 { "OK  " } else { "FALLO" }, serie.len());
    assert_eq!(serie.len(), 200, "deben sobrevivir los 200 hechos");

    // ── 3. La cadena sigue intacta ──
    let cadena_ok = hechos_store::verificar_serie(&serie).is_ok();
    println!("[{}] cadena intacta tras reabrir",
        if cadena_ok { "OK  " } else { "FALLO" });
    assert!(cadena_ok);

    // ── 4. Las firmas sobreviven y verifican ──
    let con_firma: Vec<_> = serie.iter().filter(|h| h.firma.is_some()).collect();
    println!("[{}] firmas conservadas -> {}",
        if con_firma.len() == 2 { "OK  " } else { "FALLO" }, con_firma.len());
    assert_eq!(con_firma.len(), 2);

    let verificadas = hechos_store::verificar_serie_con_firmas(&serie, &clave)
        .expect("firmas validas tras reabrir");
    println!("[{}] firmas verifican con la clave del barco -> {}",
        if verificadas == 2 { "OK  " } else { "FALLO" }, verificadas);
    assert_eq!(verificadas, 2);

    // ── 5. Manipular en disco y detectarlo ──
    drop(host);
    let mut host2 = MemoryHost::from_lmdb(&dir_s).expect("reabrir para manipular");
    // Se reescribe el valor dejando el mismo prev_hash: la cadena debe romperse.
    let serie_tmp = hechos_store::leer_serie(&host2, "BARCO-A", "gps");
    let h50 = &serie_tmp[50];
    let mut manipulado = hecho("BARCO-A", 50, "lat=99.999", &h50.prev_hash);
    // Se conserva la instancia del original para sobrescribir SU clave.
    manipulado.instance_id = h50.instance_id.clone();
    manipulado.version = h50.version;
    hechos_store::guardar(&mut host2, &manipulado)
        .expect("sobrescribir el hecho 50");
    drop(host2);

    let host3 = MemoryHost::from_lmdb(&dir_s).expect("reabrir tras manipular");
    let serie3 = hechos_store::leer_serie(&host3, "BARCO-A", "gps");
    let detectado = hechos_store::verificar_serie(&serie3).is_err();
    println!("[{}] manipulacion en disco detectada",
        if detectado { "OK  " } else { "FALLO" });
    assert!(detectado, "un valor manipulado en disco debe romper la cadena");

    println!("==================================================================");

    let _ = std::fs::remove_dir_all(&dir);
}
