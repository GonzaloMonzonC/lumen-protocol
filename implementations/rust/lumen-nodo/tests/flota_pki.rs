//! Prueba END-TO-END de la PKI de flota (`identity=pubkey` + raíz de armador).
//!
//! El escenario que importa para un armador:
//!   1. La armadora genera su raíz y su semilla les sirve para emitir
//!      certificados de sus barcos.
//!   2. Cada barco tiene SU clave.
//!   3. Un barco acepta a otro si su clave cuelga de la raíz del armador.
//!   4. Un barco de OTRA flota se rechaza aunque su firma sea perfecta.
//!   5. Un impostor que se hace pasar por un barco de la flota se rechaza.
//!
//! El punto 4 es el que hace que esto sirva para un armador: la firma buena no
//! basta; tiene que ser **de esta flota**.

use lumen_nodo_lib::identidad::{CertificadoFlota, ErrorIdentidad, Identidad};

#[test]
fn una_flota_entera_funciona_y_las_ajenas_se_rechazan() {
    // ── La armadora ───────────────────────────────────────────────
    let raiz = Identidad::generar();
    let raiz_pub = raiz.clave_publica_hex();

    // ── Dos barcos de la flota, cada uno con su clave ─────────────
    let barco_a = Identidad::generar();
    let barco_b = Identidad::generar();

    let cert_a =
        CertificadoFlota::emitir(&raiz, "Armadora Demo", "ESTRELLA", &barco_a.clave_publica_hex())
            .expect("emitir A");
    let cert_b =
        CertificadoFlota::emitir(&raiz, "Armadora Demo", "SIRIUS", &barco_b.clave_publica_hex())
            .expect("emitir B");

    // ── B acepta a A: firma del barco + pertenencia a la flota ────
    let muestra = b"^FLOTA(ESTRELLA,lat,1)=41.38";
    let firma_a = barco_a.firmar_hex(muestra);
    assert!(
        lumen_nodo_lib::identidad::verificar_miembro(&cert_a, &raiz_pub, muestra, &firma_a).is_ok(),
        "un barco de la flota debe ser aceptado"
    );

    // Y A acepta a B (no es jerárquico entre barcos).
    let muestra_b = b"^FLOTA(SIRIUS,lat,1)=40.0";
    let firma_b = barco_b.firmar_hex(muestra_b);
    assert!(lumen_nodo_lib::identidad::verificar_miembro(
        &cert_b, &raiz_pub, muestra_b, &firma_b
    )
    .is_ok());
}

#[test]
fn un_barco_de_otra_flota_se_rechaza_aunque_firme_bien() {
    let raiz_nuestra = Identidad::generar();
    let raiz_ajena = Identidad::generar();

    let barco_ajeno = Identidad::generar();
    // Su certificado es perfectamente válido... para SU armador.
    let cert_ajeno = CertificadoFlota::emitir(
        &raiz_ajena,
        "Otra Armadora",
        "INTRUSO",
        &barco_ajeno.clave_publica_hex(),
    )
    .expect("emitir");

    let muestra = b"^FLOTA(INTRUSO,lat,1)=0";
    let firma = barco_ajeno.firmar_hex(muestra); // firma correcta

    let r = lumen_nodo_lib::identidad::verificar_miembro(
        &cert_ajeno,
        &raiz_nuestra.clave_publica_hex(),
        muestra,
        &firma,
    );
    assert!(
        matches!(r, Err(ErrorIdentidad::NoPerteneceALaFlota { .. })),
        "debe rechazarse por flota, no por firma: {r:?}"
    );
}

#[test]
fn un_impostor_no_puede_firmar_como_un_barco_de_la_flota() {
    let raiz = Identidad::generar();
    let barco = Identidad::generar();
    let cert =
        CertificadoFlota::emitir(&raiz, "Armadora", "ESTRELLA", &barco.clave_publica_hex()).unwrap();

    // El impostor presenta el certificado BUENO del barco (es público), pero
    // firma con su propia clave.
    let impostor = Identidad::generar();
    let muestra = b"^FLOTA(ESTRELLA,lat,1)=0";
    let firma_falsa = impostor.firmar_hex(muestra);

    let r = lumen_nodo_lib::identidad::verificar_miembro(
        &cert,
        &raiz.clave_publica_hex(),
        muestra,
        &firma_falsa,
    );
    assert!(
        matches!(r, Err(ErrorIdentidad::FirmaNoVerifica)),
        "la firma no es de la clave del certificado: {r:?}"
    );
}

#[test]
fn cambiar_el_nombre_del_barco_en_el_certificado_lo_invalida() {
    // Esto prueba que el nombre va DENTRO de lo firmado: si no fuera así,
    // alguien podría reutilizar el certificado de un barco para otro.
    let raiz = Identidad::generar();
    let barco = Identidad::generar();
    let mut cert =
        CertificadoFlota::emitir(&raiz, "Armadora", "ESTRELLA", &barco.clave_publica_hex()).unwrap();
    cert.barco = "SIRIUS".into();
    assert!(
        cert.verificar_con_raiz(&raiz.clave_publica_hex()).is_err(),
        "renombrar el barco debe invalidar la firma"
    );
}

#[test]
fn la_semilla_reconstruye_la_misma_identidad_y_firma_igual() {
    // Lo que permite guardar la identidad en la PDB: la semilla basta.
    let id = Identidad::generar();
    let semilla = id.semilla_hex();
    let recuperada = Identidad::desde_hex(&semilla).expect("desde semilla");

    assert_eq!(id.clave_publica_hex(), recuperada.clave_publica_hex());
    let msg = b"^FLOTA(B,lat,1)=1";
    assert_eq!(
        id.firmar_hex(msg),
        recuperada.firmar_hex(msg),
        "la misma semilla debe producir la misma firma (Ed25519 es determinista)"
    );
}

#[test]
fn el_certificado_sobrevive_al_viaje_por_texto_plano() {
    // El certificado viaja en un subíndice de la PDB como texto: si no
    // sobreviviera el viaje, el formato no serviría.
    let raiz = Identidad::generar();
    let barco = Identidad::generar();
    let cert =
        CertificadoFlota::emitir(&raiz, "Armadora Demo", "ESTRELLA", &barco.clave_publica_hex())
            .unwrap();

    let texto = cert.a_texto();
    assert!(!texto.contains('\n'), "no debe tener saltos de linea");
    let leido = CertificadoFlota::desde_texto(&texto).expect("releer");
    assert_eq!(leido, cert);
    assert!(leido.verificar_con_raiz(&raiz.clave_publica_hex()).is_ok());
}
