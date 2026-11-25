//! VERIFICACIÓN DE FLOTA de punta a punta.
//!
//! El caso completo del paper: un armador con una raíz, varios barcos
//! certificados por ella, y un hub que solo acepta bitácoras de SU flota.
//!
//! Lo que se prueba y por qué importa cada cosa:
//!   1. Un barco de la flota: su bitácora se acepta.
//!   2. Un barco de OTRA flota: se rechaza aunque firme perfectamente.
//!   3. Un impostor sin certificado: se rechaza.
//!   4. Un certificado manipulado (otro nombre de barco): se rechaza.
//!   5. Un barco de la flota firmando a nombre de otro: se rechaza.
//!
//! El punto 5 es el que no se cubría antes: teniendo un certificado válido, se
//! podían firmar hechos a nombre de cualquier otro nodo.

#![cfg(feature = "motor-lmdb")]

use lumen_mlight::{Host, MemoryHost};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::{CertificadoFlota, Identidad};
use lumen_nodo_lib::replicacion::Hecho;

const MUESTRAS: u64 = 300;
const BLOQUE: u64 = 100;

fn dir_unico(tag: &str) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("lumen-flota-{}-{}", tag, std::process::id()));
    std::fs::create_dir_all(&d).unwrap();
    d
}

/// Construye una serie firmada por bloque con la identidad dada.
fn serie_firmada(nodo: &str, id: &Identidad, n: u64) -> Vec<Hecho> {
    let mut serie = Vec::with_capacity(n as usize);
    let mut prev = String::new();
    for i in 0..n {
        let h = Hecho {
            nodo: nodo.into(),
            serie: "gps".into(),
            seq: i,
            clave: "gps".into(),
            valor: format!("lat={:.6}", 41.0 + (i as f64) * 1e-6),
            prev_hash: prev.clone(),
            ts: i,
            firma: None, ..Default::default() };
        prev = h.hash();
        serie.push(h);
    }
    hechos_wire::firmar_bloque(&mut serie, BLOQUE as usize, id);
    serie
}

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

#[test]
fn solo_se_aceptan_bitacoras_de_la_flota() {
    println!();
    println!("==================================================================");
    println!("VERIFICACION DE FLOTA — armador, barcos certificados y un hub");
    println!("==================================================================");

    // ══ El armador y su raíz ══
    let raiz_armador = Identidad::generar();
    let raiz_pub = raiz_armador.clave_publica_hex();
    let armador = "Naviera Ejemplo";

    // ══ Barcos de la flota ══
    let barco_a = Identidad::generar();
    let barco_b = Identidad::generar();
    let cert_a = CertificadoFlota::emitir(&raiz_armador, armador, "BARCO-A", &barco_a.clave_publica_hex())
        .expect("certificado de A");
    let cert_b = CertificadoFlota::emitir(&raiz_armador, armador, "BARCO-B", &barco_b.clave_publica_hex())
        .expect("certificado de B");

    // ══ Un barco de OTRA flota (otro armador) ══
    let raiz_ajena = Identidad::generar();
    let barco_ajeno = Identidad::generar();
    let cert_ajeno = CertificadoFlota::emitir(
        &raiz_ajena, "Otra Naviera", "BARCO-X", &barco_ajeno.clave_publica_hex())
        .expect("certificado ajeno");

    let serie_a = serie_firmada("BARCO-A", &barco_a, MUESTRAS);

    // ══ 1. Un barco de mi flota: se acepta ══
    let r1 = hechos_wire::verificar_serie_de_flota(&serie_a, &cert_a, &raiz_pub, BLOQUE as usize);
    println!("[{}] barco de MI flota -> bitacora aceptada ({} sellos)",
        marca(r1.is_ok()), r1.as_ref().copied().unwrap_or(0));
    assert!(r1.is_ok(), "un barco de la flota debe aceptarse: {:?}", r1.err());
    assert_eq!(r1.unwrap(), (MUESTRAS / BLOQUE) as usize);

    // ══ 2. Un barco de OTRA flota: se rechaza aunque firme bien ══
    let serie_ajena = serie_firmada("BARCO-X", &barco_ajeno, MUESTRAS);
    let r2 = hechos_wire::verificar_serie_de_flota(
        &serie_ajena, &cert_ajeno, &raiz_pub, BLOQUE as usize);
    println!("[{}] barco de OTRA flota -> rechazado: {}",
        marca(r2.is_err()), r2.as_ref().err().map(|e| e.chars().take(45).collect::<String>()).unwrap_or_default());
    assert!(r2.is_err(), "un barco de otra flota NO debe aceptarse");

    // ══ 3. Un impostor SIN certificado: se rechaza ══
    let impostor = Identidad::generar();
    let serie_impostor = serie_firmada("BARCO-Z", &impostor, MUESTRAS);
    // El impostor presenta el certificado de A, pero la firma no es de A.
    let r3 = hechos_wire::verificar_serie_de_flota(
        &serie_impostor, &cert_a, &raiz_pub, BLOQUE as usize);
    println!("[{}] impostor con certificado prestado -> rechazado: {}",
        marca(r3.is_err()), r3.as_ref().err().map(|e| e.chars().take(45).collect::<String>()).unwrap_or_default());
    assert!(r3.is_err(), "un impostor NO debe colarse con el certificado de otro");

    // ══ 4. Certificado manipulado: cambiar el nombre del barco ══
    let mut cert_manipulado = cert_a.clone();
    cert_manipulado.barco = "BARCO-B".into();
    let r4 = hechos_wire::verificar_serie_de_flota(
        &serie_a, &cert_manipulado, &raiz_pub, BLOQUE as usize);
    println!("[{}] certificado con el nombre cambiado -> rechazado: {}",
        marca(r4.is_err()), r4.as_ref().err().map(|e| e.chars().take(45).collect::<String>()).unwrap_or_default());
    assert!(r4.is_err(), "un certificado manipulado NO debe valer");

    // ══ 5. Barco de la flota firmando a nombre de OTRO ══
    // BARCO-B tiene certificado valido, pero firma hechos diciendo ser BARCO-A.
    // Sin la comprobacion de nodo==certificado.barco, esto pasaria.
    let serie_suplantacion = serie_firmada("BARCO-A", &barco_b, MUESTRAS);
    let r5 = hechos_wire::verificar_serie_de_flota(
        &serie_suplantacion, &cert_b, &raiz_pub, BLOQUE as usize);
    println!("[{}] barco de la flota suplantando a otro -> rechazado: {}",
        marca(r5.is_err()), r5.as_ref().err().map(|e| e.chars().take(60).collect::<String>()).unwrap_or_default());
    assert!(r5.is_err(), "un barco NO debe poder firmar a nombre de otro");

    println!("==================================================================");
}

#[test]
fn la_bitacora_verificada_se_guarda_en_el_hub() {
    // El flujo completo: barco -> cable -> hub, con verificacion de flota
    // ANTES de guardar. Si no pertenece a la flota, no se guarda nada.
    let raiz = Identidad::generar();
    let raiz_pub = raiz.clave_publica_hex();
    let barco = Identidad::generar();
    let cert = CertificadoFlota::emitir(&raiz, "Armador", "BARCO-A", &barco.clave_publica_hex()).unwrap();

    let d_barco = dir_unico("barco-ok");
    let d_hub = dir_unico("hub-ok");

    // El barco escribe.
    let serie = serie_firmada("BARCO-A", &barco, MUESTRAS);
    {
        let mut host = MemoryHost::from_lmdb(&d_barco.to_string_lossy()).unwrap();
        for h in &serie {
            hechos_store::guardar(&mut host, h).unwrap();
        }
    }
    let host_barco = MemoryHost::from_lmdb(&d_barco.to_string_lossy()).unwrap();
    let leidos = hechos_store::leer_serie(&host_barco, "BARCO-A", "gps");

    // El hub PRIEDE la serie y verifica la flota.
    let verificacion = hechos_wire::verificar_serie_de_flota(
        &leidos, &cert, &raiz_pub, BLOQUE as usize);
    println!();
    println!("  verificacion de flota antes de guardar: {:?}", verificacion.as_ref().map(|n| format!("{n} sellos")));
    assert!(verificacion.is_ok());

    // Solo si verifica, se guarda.
    {
        let mut host_hub = MemoryHost::from_lmdb(&d_hub.to_string_lossy()).unwrap();
        let mensajes: Vec<_> = leidos.iter().map(hechos_wire::mensaje_de_hecho).collect();
        let r = hechos_wire::recibir_hechos_con(
            &mut host_hub, &mensajes, Some(&barco.clave_publica()), false);
        println!("  hub acepta: {} de {}", r.aceptados, MUESTRAS);
        assert_eq!(r.aceptados, MUESTRAS as usize);
    }
    let host_hub = MemoryHost::from_lmdb(&d_hub.to_string_lossy()).unwrap();
    let en_hub = hechos_store::contar_serie(&host_hub, "BARCO-A", "gps");
    println!("  bitacora en el hub: {} muestras", en_hub);
    assert_eq!(en_hub, MUESTRAS);

    // Y el certificado sobrevive al viaje por texto plano.
    let texto = cert.a_texto();
    let vuelta = CertificadoFlota::desde_texto(&texto).expect("certificado debe parsear");
    vuelta.verificar_con_raiz(&raiz_pub).expect("y seguir valiendo");
    println!("  el certificado sobrevive al viaje por texto: OK");

    drop(host_hub); drop(host_barco);
    for d in [d_barco, d_hub] { let _ = std::fs::remove_dir_all(d); }
}
