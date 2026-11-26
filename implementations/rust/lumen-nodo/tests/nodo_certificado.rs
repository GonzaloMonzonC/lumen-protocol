//! El nodo REAL acepta el certificado de flota por el cable.
//!
//! Cierra la última asimetría: hasta ahora `sim_flota` mandaba `CERT|` y el nodo
//! de producción no lo entendía. Un certificado no empieza por `^`, así que caía
//! en la rama de "muestra firmada" y se interpretaba como muestra mal formada.

use lumen_nodo_lib::destino::DestinoMemoria;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::{CertificadoFlota, Identidad};
use lumen_nodo_lib::nodo;
use lumen_znet::{ddp_to_frame, DdpMessage};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

#[test]
fn el_nodo_acepta_el_certificado_y_dice_de_quien_es() {
    println!();
    println!("==================================================================");
    println!("NODO REAL: certificado de flota por el cable (CERT|)");
    println!("==================================================================");

    let armador = Identidad::generar();
    let raiz = armador.clave_publica_hex();
    let barco = Identidad::generar();
    let cert = CertificadoFlota::emitir(
        &armador, "ARMADOR-T", "BARCO-T", &barco.clave_publica_hex(),
    ).expect("certificado");

    let msg = hechos_wire::mensaje_de_certificado(&cert);

    let mut host = DestinoMemoria::default();
    let mut lineas: Vec<String> = Vec::new();
    let (tipo, _num, payload) = ddp_to_frame(&msg);
    let resp = nodo::procesar(
        tipo,
        &payload,
        &mut host,
        false,
        None,
        None,
        Some(&raiz),
        &mut |s: &str| lineas.push(s.to_string()),
    );

    let ok = resp.kind == 2 || lineas.iter().any(|l| l.contains("certificado OK"));
    println!("[{}] respuesta={:?} log={:?}", marca(ok), resp.kind, lineas);
    assert!(ok, "el nodo debe aceptar el certificado: {lineas:?}");
    assert!(
        lineas.iter().any(|l| l.contains("BARCO-T") && l.contains("ARMADOR-T")),
        "el log debe decir de que barco y armador es: {lineas:?}"
    );
}

#[test]
fn un_certificado_de_otra_raiz_se_rechaza() {
    let armador = Identidad::generar();
    let raiz = armador.clave_publica_hex();
    let otro = Identidad::generar();
    let barco = Identidad::generar();

    // Emitido por OTRO armador.
    let cert = CertificadoFlota::emitir(
        &otro, "AJENO", "BARCO-T", &barco.clave_publica_hex(),
    ).expect("certificado");
    let msg = hechos_wire::mensaje_de_certificado(&cert);

    let mut host = DestinoMemoria::default();
    let mut lineas: Vec<String> = Vec::new();
    let (tipo, _num, payload) = ddp_to_frame(&msg);
    let resp = nodo::procesar(
        tipo, &payload, &mut host, false, None, None,
        Some(&raiz),
        &mut |s: &str| lineas.push(s.to_string()),
    );

    println!();
    println!("[{}] certificado de OTRA raiz -> rechazado: {:?}",
        marca(lineas.iter().any(|l| l.contains("rechazado"))), lineas);
    assert!(
        lineas.iter().any(|l| l.contains("rechazado")),
        "un certificado de otra flota debe rechazarse: {lineas:?}"
    );
}

#[test]
fn sin_raiz_configurada_el_certificado_no_se_acepta() {
    // Un nodo que no sabe de flotas no puede validar pertenencia: se rechaza en
    // vez de dar por bueno algo que no puede comprobar.
    let armador = Identidad::generar();
    let barco = Identidad::generar();
    let cert = CertificadoFlota::emitir(
        &armador, "A", "BARCO-T", &barco.clave_publica_hex(),
    ).expect("certificado");
    let msg = hechos_wire::mensaje_de_certificado(&cert);

    let mut host = DestinoMemoria::default();
    let mut lineas: Vec<String> = Vec::new();
    let (tipo, _num, payload) = ddp_to_frame(&msg);
    let _ = nodo::procesar(
        tipo, &payload, &mut host, false, None, None,
        None, // sin raiz
        &mut |s: &str| lineas.push(s.to_string()),
    );

    println!();
    println!("[{}] sin raiz -> no se puede verificar: {:?}",
        marca(lineas.iter().any(|l| l.contains("no tiene") || l.contains("rechazado"))), lineas);
    assert!(
        lineas.iter().any(|l| l.contains("rechazado")),
        "sin raiz debe rechazar, no dar por bueno: {lineas:?}"
    );
}
