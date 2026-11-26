//! VERIFICACIÓN DE FLOTA EN LA RECEPCIÓN.
//!
//! ## El agujero que cierra
//!
//! Antes, el hub comprobaba cadena y firmas. Con eso sabía que **alguien con una
//! clave** escribió los hechos. Pero cualquiera puede generarse un par Ed25519,
//! firmar 300 muestras encadenadas y firmadas correctamente, y el hub las acepta.
//!
//! La criptografía estaba bien. Faltaba la confianza: **¿esa clave es de un
//! barco de mi flota?**

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::{CertificadoFlota, Identidad};
use lumen_nodo_lib::replicacion::Hecho;

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

/// Construye una serie firmada de `n` hechos, con un certificado si se pide.
fn preparar(
    nodo: &str,
    id: &Identidad,
    n: u64,
    certificado: Option<&CertificadoFlota>,
) -> Vec<lumen_znet::DdpMessage> {
    let mut msgs = Vec::new();
    if let Some(c) = certificado {
        // El certificado va PRIMERO: el hub lo necesita antes de verificar.
        msgs.push(hechos_wire::mensaje_de_certificado(c));
    }
    let mut prev = String::new();
    for i in 0..n {
        let mut h = Hecho::v2(nodo, "gps", i, "inst-A", 0, "gps",
                              &format!("lat=41.{i}"), &prev, i);
        h.firmar(id);
        prev = h.hash();
        msgs.push(hechos_wire::mensaje_de_hecho(&h));
    }
    msgs
}

#[test]
fn un_barco_de_la_flota_se_acepta() {
    println!();
    println!("==================================================================");
    println!("VERIFICACION DE FLOTA EN LA RECEPCION");
    println!("==================================================================");

    let armador = Identidad::generar();
    let raiz = armador.clave_publica_hex();
    let barco = Identidad::generar();
    let cert = CertificadoFlota::emitir(&armador, "ARMADOR", "BARCO-A", &barco.clave_publica_hex()).expect("cert");

    let msgs = preparar("BARCO-A", &barco, 5, Some(&cert));
    let mut host = MemoryHost::default();
    let r = hechos_wire::recibir_hechos_de_flota(&mut host, &msgs, &raiz, 100, false);

    let guardados = hechos_store::leer_serie_de_rama(&host, "BARCO-A", "gps", "inst-A").len();
    println!("[{}] barco de la flota -> aceptados={} rechazados={} guardados={}",
        marca(r.aceptados == 5 && guardados == 5), r.aceptados, r.rechazados, guardados);
    assert_eq!(r.aceptados, 5, "un barco certificado debe entrar: {:?}", r.primer_motivo);
    assert_eq!(guardados, 5);
}

#[test]
fn sin_certificado_se_rechaza_todo() {
    // ESTE es el agujero: una clave válida pero sin pertenencia probada.
    let armador = Identidad::generar();
    let raiz = armador.clave_publica_hex();
    let impostor = Identidad::generar();

    let msgs = preparar("BARCO-X", &impostor, 5, None);
    let mut host = MemoryHost::default();
    let r = hechos_wire::recibir_hechos_de_flota(&mut host, &msgs, &raiz, 100, false);

    let guardados = hechos_store::leer_serie_de_rama(&host, "BARCO-X", "gps", "inst-A").len();
    println!("[{}] clave valida SIN certificado -> aceptados={} guardados={} motivo={:?}",
        marca(r.aceptados == 0 && guardados == 0), r.aceptados, guardados,
        r.primer_motivo.as_deref().map(|m| &m[..40.min(m.len())]));
    assert_eq!(r.aceptados, 0, "sin certificado NO debe entrar nada");
    assert_eq!(guardados, 0, "y no debe quedar nada guardado");
}

#[test]
fn un_certificado_de_otra_flota_se_rechaza() {
    let armador = Identidad::generar();
    let raiz = armador.clave_publica_hex();
    let otro_armador = Identidad::generar();
    let barco = Identidad::generar();

    // Certificado emitido por OTRO armador.
    let cert_ajeno = CertificadoFlota::emitir(&otro_armador, "OTRO-ARMADOR", "BARCO-A", &barco.clave_publica_hex()).expect("cert");

    let msgs = preparar("BARCO-A", &barco, 5, Some(&cert_ajeno));
    let mut host = MemoryHost::default();
    let r = hechos_wire::recibir_hechos_de_flota(&mut host, &msgs, &raiz, 100, false);

    println!();
    println!("[{}] certificado de OTRA flota -> aceptados={} rechazados={}",
        marca(r.aceptados == 0), r.aceptados, r.rechazados);
    assert_eq!(r.aceptados, 0, "un certificado ajeno no debe valer");
}

#[test]
fn un_barco_no_puede_firmar_a_nombre_de_otro() {
    // Un miembro legítimo abusando de su legitimidad: su clave es válida y está
    // certificada, pero firma hechos a nombre de otro barco.
    let armador = Identidad::generar();
    let raiz = armador.clave_publica_hex();
    let barco_a = Identidad::generar();

    // Certificado de BARCO-A, pero los hechos dicen BARCO-B.
    let cert = CertificadoFlota::emitir(&armador, "ARMADOR", "BARCO-A", &barco_a.clave_publica_hex()).expect("cert");
    let msgs = preparar("BARCO-B", &barco_a, 5, Some(&cert));

    let mut host = MemoryHost::default();
    let r = hechos_wire::recibir_hechos_de_flota(&mut host, &msgs, &raiz, 100, false);

    println!();
    println!("[{}] certificado de A, hechos de B -> aceptados={} rechazados={}",
        marca(r.aceptados == 0), r.aceptados, r.rechazados);
    println!("      motivo: {:?}", r.primer_motivo.as_deref().map(|m| &m[..60.min(m.len())]));
    assert_eq!(r.aceptados, 0, "no se puede firmar a nombre de otro barco");
}

#[test]
fn el_certificado_va_y_vuelve_por_el_cable() {
    let armador = Identidad::generar();
    let barco = Identidad::generar();
    let cert = CertificadoFlota::emitir(&armador, "ARMADOR", "BARCO-A", &barco.clave_publica_hex()).expect("cert");

    let m = hechos_wire::mensaje_de_certificado(&cert);
    let vuelta = hechos_wire::certificado_de_mensaje(&m).expect("debe parsearse");

    println!();
    println!("  certificado por el cable: barco={} armador={}",
        vuelta.barco, vuelta.armador);
    assert_eq!(vuelta.barco, "BARCO-A");
    assert_eq!(vuelta.armador, "ARMADOR");
    vuelta.verificar_con_raiz(&armador.clave_publica_hex())
        .expect("debe verificar contra su raiz");
}
