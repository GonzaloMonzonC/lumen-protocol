//! Cableado: las cuatro piezas conectadas entre sí.
//!
//! Hasta ahora cada pieza estaba probada por separado. Aquí se prueba que
//! **se llaman**: recibir aplica la cota y los conflictos quedan persistidos.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::conflicto::{motivo_de_hecho, SERIE_CONFLICTOS};
use lumen_nodo_lib::cota_epoch::Cota;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire::{persistir_conflictos, recibir_hechos_con_cota};
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, TipoHecho};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

fn mensaje(h: &Hecho) -> lumen_znet::DdpMessage {
    lumen_nodo_lib::hechos_wire::mensaje_de_hecho(h)
}

#[test]
fn un_epoch_fuera_de_cota_no_se_guarda() {
    println!();
    println!("==================================================================");
    println!("CABLEADO — las piezas se llaman entre si");
    println!("==================================================================");

    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    // Un hecho con epoch imposible para su posición.
    let mut h = Hecho::v3(
        "DRON-X", "gps", 0, "inst-mala", 5000, "gps", "lat=99", "", 100,
        TipoHecho::Idempotente,
    );
    h.firmar(&id);

    let r = recibir_hechos_con_cota(
        &mut host, &[mensaje(&h)], None, false, Some(Cota::default()),
    );

    let guardados = hechos_store::leer_serie_de_rama(&host, "DRON-X", "gps", "inst-mala").len();
    println!("    aceptados={} en_cuarentena={} guardados={}",
        r.aceptados, r.en_cuarentena, guardados);
    println!("[{}] el epoch fuera de cota NO llega al store",
        marca(r.en_cuarentena == 1 && guardados == 0));
    println!("[{}] la rama queda anotada para cuarentena",
        marca(!r.cuarentena.is_empty()));
    if let Some((inst, motivo)) = r.cuarentena.first() {
        println!("      instancia: {inst}");
        println!("      motivo: {}...", &motivo[..60.min(motivo.len())]);
    }

    assert_eq!(r.en_cuarentena, 1, "debe apartarse");
    assert_eq!(guardados, 0, "no debe guardarse nada");
    assert!(!r.cuarentena.is_empty());
}

#[test]
fn un_epoch_normal_se_sigue_guardando() {
    // La cota no puede romper el caso normal.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    let mut h = Hecho::v3("DRON-1", "gps", 0, "inst-A", 0, "gps", "lat=41", "", 100,
        TipoHecho::Idempotente);
    h.firmar(&id);

    let r = recibir_hechos_con_cota(&mut host, &[mensaje(&h)], None, false, Some(Cota::default()));
    let guardados = hechos_store::leer_serie_de_rama(&host, "DRON-1", "gps", "inst-A").len();

    println!();
    println!("[{}] epoch normal: aceptados={} guardados={}",
        marca(r.aceptados == 1 && guardados == 1), r.aceptados, guardados);
    assert_eq!(r.aceptados, 1);
    assert_eq!(guardados, 1);
}

#[test]
fn sin_cota_todo_funciona_como_antes() {
    // El parametro es opcional: no rompe a quien no la usa.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let mut h = Hecho::v3("DRON-1", "gps", 0, "inst-A", 999999, "gps", "x", "", 100,
        TipoHecho::Idempotente);
    h.firmar(&id);

    let r = recibir_hechos_con_cota(&mut host, &[mensaje(&h)], None, false, None);
    println!();
    println!("[{}] sin cota, un epoch alto se acepta (compatibilidad)",
        marca(r.aceptados == 1));
    assert_eq!(r.aceptados, 1);
}

#[test]
fn los_conflictos_detectados_quedan_persistidos() {
    // EL AGUJERO QUE CIERRA: antes quedaban solo en el resumen (memoria).
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    // Dos ramas en la misma posición, con valores distintos.
    let mut a = Hecho::v3("DRON-1", "reserva", 0, "inst-A", 0, "celda", "dueno=A", "", 100,
        TipoHecho::RecursoExclusivo);
    a.firmar(&id);
    let mut b = Hecho::v3("DRON-1", "reserva", 0, "inst-B", 0, "celda", "dueno=B", "", 101,
        TipoHecho::RecursoExclusivo);
    b.firmar(&id);

    let r1 = recibir_hechos_con_cota(&mut host, &[mensaje(&a)], None, false, None);
    let r2 = recibir_hechos_con_cota(&mut host, &[mensaje(&b)], None, false, None);
    let total_conflictos = r1.conflictos + r2.conflictos;

    println!();
    println!("  conflictos detectados: {total_conflictos}");
    println!("  detalle en el resumen: {}", r2.detalle_conflictos.len() + r1.detalle_conflictos.len());

    // Antes: esto se perdia. Ahora se persiste.
    let mut todos = r1.detalle_conflictos.clone();
    todos.extend(r2.detalle_conflictos.clone());
    let mut resumen = r2.clone();
    resumen.detalle_conflictos = todos;

    let n = persistir_conflictos(&mut host, &resumen, "HUB-1", "hub", 0, 2000, Some(&id));
    println!("[{}] conflictos persistidos como hechos: {n}", marca(n > 0));

    let guardados = hechos_store::leer_serie_de_rama(&host, "HUB-1", SERIE_CONFLICTOS, "hub");
    println!("[{}] y se pueden releer del store: {} hecho(s)",
        marca(!guardados.is_empty()), guardados.len());

    for h in &guardados {
        let m = motivo_de_hecho(h);
        println!("      {} -> motivo {:?}", h.clave, m);
        assert!(m.is_some());
    }
    assert!(!guardados.is_empty(), "los conflictos deben quedar guardados");
    assert_eq!(guardados.len(), n);
}

#[test]
fn los_conflictos_persistidos_sobreviven_al_reinicio() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    let mut a = Hecho::v3("DRON-1", "reserva", 0, "inst-A", 0, "celda", "dueno=A", "", 100,
        TipoHecho::RecursoExclusivo);
    a.firmar(&id);
    let mut b = Hecho::v3("DRON-1", "reserva", 0, "inst-B", 0, "celda", "dueno=B", "", 101,
        TipoHecho::RecursoExclusivo);
    b.firmar(&id);

    let r1 = recibir_hechos_con_cota(&mut host, &[mensaje(&a)], None, false, None);
    let mut resumen = recibir_hechos_con_cota(&mut host, &[mensaje(&b)], None, false, None);
    let mut todos = r1.detalle_conflictos;
    todos.extend(resumen.detalle_conflictos.clone());
    resumen.detalle_conflictos = todos;

    let n = persistir_conflictos(&mut host, &resumen, "HUB-1", "hub", 0, 2000, Some(&id));
    assert!(n > 0);

    // Simular reinicio: releer del mismo store.
    let releidos = hechos_store::leer_serie_de_rama(&host, "HUB-1", SERIE_CONFLICTOS, "hub");
    println!();
    println!("[{}] tras 'reiniciar', {}/{} conflictos siguen legibles",
        marca(releidos.len() == n), releidos.len(), n);
    assert_eq!(releidos.len(), n);

    // Y con la cadena intacta.
    let ok = hechos_store::verificar_serie(&releidos).is_ok();
    println!("[{}] la cadena de conflictos verifica", marca(ok));
    assert!(ok);
}
