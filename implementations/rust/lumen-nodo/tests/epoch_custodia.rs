//! CADENA DE CUSTODIA DEL EPOCH — el agujero de "subir el epoch a lo bruto".
//!
//! ## Qué se prueba
//!
//! 1. Un barco que reinstala (epoch 1) con su salto firmado: **se acepta**.
//! 2. Un barco que declara epoch 999 **sin cadena**: se **rechaza**.
//! 3. Un salto firmado por otro nodo: **no vale**.
//! 4. Un salto de más de uno: **no vale**.
//! 5. Retroceder de epoch: **no vale**.
//!
//! ## Por qué importa
//!
//! Sin esto, cualquiera con la clave del barco puede declarar `epoch=999999` y
//! ganar siempre. El epoch es el orden entre historias; si lo decide quien grita
//! más alto, no hay orden.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::epoch::{verificar_cadena, Custodia, SaltoEpoch};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::Hecho;

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

fn hecho_con_epoch(inst: &str, epoch: u64, seq: u64, prev: &str) -> Hecho {
    Hecho::v2("BARCO-A", "gps", seq, inst, epoch, "gps",
              &format!("lat=41.{seq}"), prev, seq)
}

#[test]
fn el_epoch_no_se_puede_subir_a_lo_bruto() {
    println!();
    println!("==================================================================");
    println!("CUSTODIA DEL EPOCH");
    println!("==================================================================");

    let barco = Identidad::generar();
    let clave = barco.clave_publica_hex();

    // ── 1. Reinstalación legítima: epoch 1 con salto firmado ──
    let salto = SaltoEpoch::crear(0, 1, "inst-NUEVA", &barco).expect("crear salto");
    let c = verificar_cadena(0, 1, std::slice::from_ref(&salto), &clave);
    println!("[{}] reinstalacion con salto firmado (0->1) -> {:?}",
        marca(c.es_valido()), c);
    assert!(c.es_valido(), "una reinstalacion legitima debe aceptarse");

    // ── 2. EL AGUJERO: epoch 999 sin cadena ──
    let c = verificar_cadena(0, 999, &[], &clave);
    println!("[{}] epoch 999 SIN cadena -> {:?}", marca(!c.es_valido()), c);
    assert!(!c.es_valido(), "subir el epoch a lo bruto NO debe valer");

    // ── 3. Salto firmado por otro nodo ──
    let impostor = Identidad::generar();
    let falso = SaltoEpoch::crear(0, 1, "inst-MALA", &impostor).expect("crear");
    let c = verificar_cadena(0, 1, std::slice::from_ref(&falso), &clave);
    println!("[{}] salto firmado por un impostor -> {:?}", marca(!c.es_valido()), c);
    assert!(!c.es_valido(), "el salto de otro nodo no debe valer");

    // ── 4. Salto de mas de uno (no se puede ni crear) ──
    let grande = SaltoEpoch::crear(0, 5, "inst-X", &barco);
    println!("[{}] salto de 0 a 5 (de golpe) -> {}",
        marca(grande.is_err()),
        if grande.is_err() { "rechazado al crear" } else { "CREADO (mal)" });
    assert!(grande.is_err(), "no se debe poder crear un salto de 5");

    // ── 5. Retroceso ──
    let c = verificar_cadena(5, 2, &[], &clave);
    println!("[{}] retroceso de epoch 5 a 2 -> {:?}", marca(!c.es_valido()), c);
    assert!(!c.es_valido(), "no se puede retroceder de epoch");

    println!("==================================================================");
}

#[test]
fn la_recepcion_aplica_la_custodia() {
    // El modulo solo no sirve: la recepcion tiene que usarlo.
    let barco = Identidad::generar();
    let clave = barco.clave_publica_hex();

    // Un barco que declara epoch 99 sin presentar cadena.
    let mut host = MemoryHost::default();
    let h = hecho_con_epoch("inst-ESTAFA", 99, 0, "");
    let msgs = vec![hechos_wire::mensaje_de_hecho(&h)];

    let r = hechos_wire::recibir_hechos_custodiados(
        &mut host, &msgs, &clave, &[], 0, false);

    println!();
    println!("  recepcion con epoch 99 sin cadena: aceptados={} rechazados={} motivo={:?}",
        r.aceptados, r.rechazados, r.primer_motivo);
    assert_eq!(r.aceptados, 0, "no debe aceptarse un epoch sin custodia");
    assert_eq!(r.rechazados, 1);
    let guardados = hechos_store::contar_serie(&host, "BARCO-A", "gps");
    assert_eq!(guardados, 0, "no debe quedar nada guardado");
    println!("  [{}] no se guardo nada en el almacen -> {} hechos",
        marca(guardados == 0), guardados);
}

#[test]
fn una_reinstalacion_legitima_si_entra() {
    // El camino bueno: el barco reinstala y presenta su salto firmado.
    let barco = Identidad::generar();
    let clave = barco.clave_publica_hex();
    let salto = SaltoEpoch::crear(0, 1, "inst-NUEVA", &barco).expect("salto");

    let mut host = MemoryHost::default();
    let mut prev = String::new();
    let mut msgs = Vec::new();
    for i in 0..5u64 {
        let h = hecho_con_epoch("inst-NUEVA", 1, i, &prev);
        prev = h.hash();
        msgs.push(hechos_wire::mensaje_de_hecho(&h));
    }

    let r = hechos_wire::recibir_hechos_custodiados(
        &mut host, &msgs, &clave, &[salto], 0, false);

    println!();
    println!("  reinstalacion legitima: aceptados={} rechazados={}",
        r.aceptados, r.rechazados);
    assert_eq!(r.aceptados, 5, "con salto valido deben entrar los 5: {:?}", r.primer_motivo);
    assert_eq!(r.rechazados, 0);

    let guardados = hechos_store::leer_serie_de_rama(&host, "BARCO-A", "gps", "inst-NUEVA");
    println!("  [{}] guardados en la rama inst-NUEVA -> {}",
        marca(guardados.len() == 5), guardados.len());
    assert_eq!(guardados.len(), 5, "los 5 deben estar en la rama de la instancia nueva");
}

#[test]
fn los_hechos_v1_no_necesitan_custodia() {
    // Un hecho v1 no tiene epoch: no se le puede exigir cadena.
    let barco = Identidad::generar();
    let clave = barco.clave_publica_hex();

    let mut host = MemoryHost::default();
    let h = Hecho::v1("BARCO-A", "gps", 0, "gps", "lat=41.0", "", 1);
    let msgs = vec![hechos_wire::mensaje_de_hecho(&h)];

    let r = hechos_wire::recibir_hechos_custodiados(
        &mut host, &msgs, &clave, &[], 0, false);

    println!();
    println!("  hecho v1 (sin epoch): aceptados={} rechazados={}",
        r.aceptados, r.rechazados);
    assert_eq!(r.aceptados, 1, "un v1 debe entrar sin cadena de custodia");
}

#[test]
fn la_cadena_completa_de_tres_saltos_verifica() {
    let barco = Identidad::generar();
    let clave = barco.clave_publica_hex();
    let saltos: Vec<SaltoEpoch> = (0..3)
        .map(|i| SaltoEpoch::crear(i, i + 1, "inst-A", &barco).unwrap())
        .collect();

    let c = verificar_cadena(0, 3, &saltos, &clave);
    println!();
    println!("  cadena 0->1->2->3 completa: {:?}", c);
    assert_eq!(c, Custodia::Valido);

    // Pero sin el salto del medio, no se llega.
    let incompleta = vec![saltos[0].clone(), saltos[2].clone()];
    let c2 = verificar_cadena(0, 3, &incompleta, &clave);
    println!("  cadena con el salto 1->2 quitado: {:?}", c2);
    assert!(!c2.es_valido(), "sin el salto intermedio no se debe llegar");
}
