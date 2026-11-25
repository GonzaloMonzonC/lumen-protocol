//! Replicación END-TO-END: dos nodos, el cable en medio, LMDB en disco.
//!
//! Lo que esto demuestra y los tests unitarios no:
//!   - El barco escribe 500 muestras EN LMDB, firmadas por bloque.
//!   - El hub pide desde seq 0 y las recibe por el transporte.
//!   - El hub las VERIFICA al recibir y las guarda en SU LMDB.
//!   - Un hecho manipulado en el cable no entra.
//!
//! Es el caso del paper: un barco que vuelve a cobertura y sincroniza su bitácora.

#![cfg(feature = "motor-lmdb")]

use lumen_mlight::{Host, MemoryHost};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::Hecho;
use lumen_znet::{msg_type, DdpMessage};

const MUESTRAS: u64 = 500;
const BLOQUE: u64 = 100;

fn dir_unico(tag: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("lumen-e2e-{}-{}", tag, std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d
}

#[test]
fn el_barco_sincroniza_su_bitacora_con_el_hub() {
    let id = Identidad::generar();
    let clave = id.clave_publica();
    let d_barco = dir_unico("barco");
    let d_hub = dir_unico("hub");

    println!();
    println!("==================================================================");
    println!("E2E · BARCO -> HUB · {} muestras, firma por bloque de {}", MUESTRAS, BLOQUE);
    println!("==================================================================");

    // ══ 1. EL BARCO escribe su bitacora en LMDB ══
    let mut serie: Vec<Hecho> = Vec::new();
    let mut prev = String::new();
    for i in 0..MUESTRAS {
        let h = Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq: i,
            clave: "gps".into(),
            valor: format!("lat={:.6}", 41.0 + (i as f64) * 1e-6),
            prev_hash: prev.clone(),
            ts: i,
            firma: None,
        };
        prev = h.hash();
        serie.push(h);
    }
    // La firma cubre el SELLO del bloque, no una muestra suelta.
    let n_bloques = hechos_wire::firmar_bloque(&mut serie, BLOQUE as usize, &id);
    {
        let mut host = MemoryHost::from_lmdb(&d_barco.to_string_lossy()).expect("lmdb barco");
        for h in &serie {
            hechos_store::guardar(&mut host, h).expect("guardar en barco");
        }
    } // se cierra el LMDB del barco: simula apagado

    let host_barco = MemoryHost::from_lmdb(&d_barco.to_string_lossy()).expect("reabrir barco");
    let total_barco = hechos_store::contar_serie(&host_barco, "BARCO-A", "gps");
    println!("[{}] el barco guardo su bitacora -> {} muestras, {} sellos firmados",
        if total_barco == MUESTRAS { "OK  " } else { "FALLO" }, total_barco, n_bloques);
    assert_eq!(total_barco, MUESTRAS);
    assert_eq!(n_bloques, (MUESTRAS / BLOQUE) as usize);

    // ══ 2. El HUB pide y recibe por el cable ══
    let peticion = hechos_wire::peticion("gps", 0);
    let (serie, desde) = hechos_wire::interpretar_peticion(&peticion).expect("peticion valida");
    assert_eq!((serie.as_str(), desde), ("gps", 0));

    // El barco sirve: un mensaje por hecho (esto es lo que iria por QUIC).
    let mut mensajes = Vec::new();
    for seq in desde..total_barco {
        let h = hechos_store::leer(&host_barco, "BARCO-A", &serie, seq).expect("hecho");
        mensajes.push(hechos_wire::mensaje_de_hecho(&h));
    }
    println!("[{}] el barco sirve los hechos por el cable -> {} mensajes",
        if mensajes.len() == MUESTRAS as usize { "OK  " } else { "FALLO" }, mensajes.len());

    // ══ 3. El HUB verifica y guarda en SU LMDB ══
    {
        let mut host_hub = MemoryHost::from_lmdb(&d_hub.to_string_lossy()).expect("lmdb hub");
        let r = hechos_wire::recibir_hechos_con(&mut host_hub, &mensajes, Some(&clave), false);
        println!("[{}] el hub verifica y acepta -> {} aceptados, {} rechazados",
            if r.aceptados == MUESTRAS as usize && r.rechazados == 0 { "OK  " } else { "FALLO" },
            r.aceptados, r.rechazados);
        assert_eq!(r.aceptados, MUESTRAS as usize, "motivo: {:?}", r.primer_motivo);
        assert_eq!(r.rechazados, 0);
    }

    let host_hub = MemoryHost::from_lmdb(&d_hub.to_string_lossy()).expect("reabrir hub");
    let serie_hub = hechos_store::leer_serie(&host_hub, "BARCO-A", "gps");
    println!("[{}] el hub tiene la bitacora completa -> {} muestras",
        if serie_hub.len() == MUESTRAS as usize { "OK  " } else { "FALLO" }, serie_hub.len());
    assert_eq!(serie_hub.len(), MUESTRAS as usize);

    // ══ 4. La cadena del hub es verificable de punta a punta, CON SELLOS ══
    hechos_store::verificar_serie(&serie_hub).expect("la cadena del hub debe verificar");
    let bloques_ok = hechos_wire::verificar_bloques(&serie_hub, BLOQUE as usize, &clave)
        .expect("los sellos de bloque deben verificar");
    println!("[{}] cadena + sellos de bloque verifican en el hub -> {} sellos",
        if bloques_ok == (MUESTRAS / BLOQUE) as usize { "OK  " } else { "FALLO" }, bloques_ok);
    assert_eq!(bloques_ok, (MUESTRAS / BLOQUE) as usize);

    // ══ 5. Un hecho manipulado en el cable NO entra ══
    //
    // Se manipula la muestra 0, que NO lleva firma propia: solo el sello del
    // bloque la cubre. Hay DOS defensas y basta con que actue una:
    //   a) la cadena de hashes: al cambiar el valor, su hash cambia y el
    //      prev_hash de la muestra 1 deja de encajar -> se rechaza al recibir.
    //   b) el sello del bloque: aunque entrara, el sello recalculado no
    //      coincidiria con el firmado.
    let d_intruso = dir_unico("intruso");
    let mut host_intruso = MemoryHost::from_lmdb(&d_intruso.to_string_lossy()).expect("lmdb intruso");
    let mut serie_mala = serie_hub.clone();
    serie_mala[0].valor = "lat=99.9".into();
    let mensajes_malos: Vec<_> = serie_mala.iter()
        .map(hechos_wire::mensaje_de_hecho).collect();
    let r_malo = hechos_wire::recibir_hechos_con(&mut host_intruso, &mensajes_malos, Some(&clave), false);
    println!("[{}] defensa (a): la cadena rechaza el hecho manipulado -> {} aceptados, {} rechazados",
        if r_malo.rechazados > 0 { "OK  " } else { "FALLO" }, r_malo.aceptados, r_malo.rechazados);
    assert!(r_malo.rechazados > 0, "la cadena debe rechazar el hecho manipulado");

    // Defensa (b): aunque el hecho entrara por otra via, el sello lo delata.
    // Se comprueba AISLADO de la cadena, para saber si el sello protege de verdad.
    let sello_roto = hechos_wire::verificar_solo_bloques(&serie_mala, BLOQUE as usize, &clave);
    let detalle = sello_roto.as_ref().err().map(|e| e.chars().take(50).collect::<String>());
    println!("[{}] defensa (b): el sello del bloque delata la manipulacion -> {:?}",
        if sello_roto.is_err() { "OK  " } else { "FALLO" }, detalle);
    assert!(sello_roto.is_err(), "el sello debe detectar la manipulacion aunque la cadena no");

    // El sello de la serie ORIGINAL si valida: la defensa no da falsos positivos.
    let sello_ok = hechos_wire::verificar_solo_bloques(&serie_hub, BLOQUE as usize, &clave);
    let n_ok = sello_ok.as_ref().copied().unwrap_or(0);
    println!("[{}] y el sello de la serie intacta valida -> {} sellos",
        if sello_ok.is_ok() { "OK  " } else { "FALLO" }, n_ok);
    assert!(sello_ok.is_ok());

    // ══ 6. Reenviar los mismos hechos no duplica (idempotencia) ══
    // LMDB no permite abrir el mismo entorno dos veces en el mismo proceso,
    // asi que se suelta el handle anterior antes de reabrir.
    drop(host_hub);
    {
        let mut host_hub2 = MemoryHost::from_lmdb(&d_hub.to_string_lossy()).expect("reabrir hub");
        let antes = hechos_store::contar_serie(&host_hub2, "BARCO-A", "gps");
        let _ = hechos_wire::recibir_hechos_con(&mut host_hub2, &mensajes[100..110], Some(&clave), false);
        let despues = hechos_store::contar_serie(&host_hub2, "BARCO-A", "gps");
        println!("[{}] reenviar no duplica -> {} antes, {} despues",
            if antes == despues { "OK  " } else { "FALLO" }, antes, despues);
        assert_eq!(antes, despues);
    }

    println!("==================================================================");

    for d in [d_barco, d_hub, d_intruso] {
        let _ = std::fs::remove_dir_all(d);
    }
}

#[test]
fn el_hub_pide_solo_lo_que_le_falta() {
    let id = Identidad::generar();
    let d = dir_unico("parcial");
    let mut host = MemoryHost::from_lmdb(&d.to_string_lossy()).expect("lmdb");

    // El hub ya tiene hasta seq 199; pide desde 200.
    let mut prev = String::new();
    for i in 0..200u64 {
        let h = Hecho {
            nodo: "BARCO-A".into(), serie: "gps".into(), seq: i, clave: "gps".into(),
            valor: format!("lat=41.{i}"), prev_hash: prev.clone(), ts: i, firma: None,
        };
        prev = h.hash();
        hechos_store::guardar(&mut host, &h).unwrap();
    }
    let peticion = hechos_wire::peticion("gps", 200);
    let (_, desde) = hechos_wire::interpretar_peticion(&peticion).unwrap();
    let total = hechos_store::contar_serie(&host, "BARCO-A", "gps");

    println!();
    println!("  el hub pide desde {} y el barco tiene {} -> pide {} hechos",
        desde, total, total - desde);
    assert_eq!(desde, 200);
    assert_eq!(total - desde, 0, "ya lo tiene todo, no debe pedir nada");
    let _ = id;
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn un_mensaje_que_no_es_de_hechos_no_rompe_nada() {
    let mut host = MemoryHost::default();
    let basura = vec![
        DdpMessage::new(msg_type::DATA, 0, 0, 0, b"cualquier cosa".to_vec()),
        DdpMessage::new(msg_type::DATA, 0, 0, 0, b"".to_vec()),
        DdpMessage::new(msg_type::DATA, 0, 0, 0, b"a|b".to_vec()),
    ];
    let r = hechos_wire::recibir_hechos(&mut host, &basura, None);
    assert_eq!(r.aceptados, 0);
    assert_eq!(r.rechazados, 3);
    println!("  mensajes basura rechazados sin panico: {}", r.rechazados);
}
