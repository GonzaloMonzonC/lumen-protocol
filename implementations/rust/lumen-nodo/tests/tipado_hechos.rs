//! Tipado de hechos: v1 y v2 siguen valiendo, v3 firma el tipo.
//!
//! ## Qué se prueba
//!
//! 1. **Retrocompatibilidad**: un hecho v1 o v2 sigue verificando su firma. Si
//!    esto se rompe, todos los hechos ya escritos quedarían invalidados.
//! 2. **El tipo va firmado**: cambiar el tipo de un hecho v3 invalida la firma.
//!    Si no fuera así, alguien podría pasar un hecho de telemetría a seguridad.
//! 3. **Regla de convergencia**: solo idempotente y conmutativo convergen solos.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, TipoHecho};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

#[test]
fn v1_y_v2_siguen_verificando_su_firma() {
    println!();
    println!("==================================================================");
    println!("TIPADO DE HECHOS — retrocompatibilidad y firma del tipo");
    println!("==================================================================");

    let id = Identidad::generar();
    let pubk = lumen_nodo_lib::identidad::hex_a_bytes_publico(&id.clave_publica_hex()).unwrap();

    // v1: sin instancia ni epoch.
    let mut h1 = Hecho::v1("NODO-1", "gps", 0, "gps", "lat=41", "", 100);
    h1.firmar(&id);
    let ok1 = h1.verificar_firma(&pubk).is_ok();
    println!("[{}] hecho v1 sigue verificando", marca(ok1));
    assert!(ok1);

    // v2: con instancia y epoch.
    let mut h2 = Hecho::v2("NODO-1", "gps", 0, "inst-A", 0, "gps", "lat=41", "", 100);
    h2.firmar(&id);
    let ok2 = h2.verificar_firma(&pubk).is_ok();
    println!("[{}] hecho v2 sigue verificando", marca(ok2));
    assert!(ok2);

    // Los dos coexisten sin problema.
    let mut host = MemoryHost::default();
    hechos_store::guardar(&mut host, &h1).expect("v1");
    hechos_store::guardar(&mut host, &h2).expect("v2");
    println!("[{}] v1 y v2 conviven en el mismo store", marca(true));
}

#[test]
fn cambiar_el_tipo_de_un_hecho_v3_invalida_la_firma() {
    // ESTA es la prueba que importa: si el tipo no fuera firmado, un atacante
    // podria convertir un hecho de telemetria en uno de seguridad y hacer que
    // la regla de convergencia le obedeciera.
    let id = Identidad::generar();
    let pubk = lumen_nodo_lib::identidad::hex_a_bytes_publico(&id.clave_publica_hex()).unwrap();

    let mut h = Hecho::v3(
        "NODO-1", "mision", 0, "inst-A", 0, "modo", "RTH", "", 100,
        TipoHecho::ConRevision,
    );
    h.firmar(&id);
    assert!(h.verificar_firma(&pubk).is_ok(), "el hecho legitimo debe verificar");

    // Manipular el tipo manteniendo la firma.
    let mut falso = h.clone();
    falso.tipo = TipoHecho::Idempotente;

    println!();
    println!("[{}] cambiar el tipo de v3 INVALIDA la firma", marca(falso.verificar_firma(&pubk).is_err()));
    assert!(
        falso.verificar_firma(&pubk).is_err(),
        "el tipo DEBE ir firmado: si no, un hecho de seguridad podria convertirse en telemetria"
    );
}

#[test]
fn el_tipo_sobrevive_a_guardar_y_releer() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let mut h = Hecho::v3(
        "NODO-1", "mision", 0, "inst-A", 0, "modo", "RTH", "", 100,
        TipoHecho::ConRevision,
    );
    h.firmar(&id);
    hechos_store::guardar(&mut host, &h).expect("guardar");

    let leido = hechos_store::leer_serie_de_rama(&host, "NODO-1", "mision", "inst-A");
    println!();
    println!("[{}] el tipo sobrevive al store: leido = {:?}",
        marca(leido.len() == 1 && leido[0].tipo == TipoHecho::ConRevision),
        leido.first().map(|x| x.tipo));
    assert_eq!(leido.len(), 1);
    assert_eq!(leido[0].tipo, TipoHecho::ConRevision);
    assert_eq!(leido[0].version, 3);
}

#[test]
fn solo_idempotente_y_conmutativo_convergen_solos() {
    // Smith: "LWW sobre seguridad es un error de categoria".
    println!();
    println!("  reglas de convergencia:");
    println!("    idem      converge solo: {}", TipoHecho::Idempotente.converge_solo());
    println!("    conm      converge solo: {}", TipoHecho::Conmutativo.converge_solo());
    println!("    recurso   converge solo: {}", TipoHecho::RecursoExclusivo.converge_solo());
    println!("    revision  converge solo: {}", TipoHecho::ConRevision.converge_solo());

    assert!(TipoHecho::Idempotente.converge_solo());
    assert!(TipoHecho::Conmutativo.converge_solo());
    assert!(!TipoHecho::RecursoExclusivo.converge_solo(), "un recurso exclusivo necesita conflicto explicito");
    assert!(!TipoHecho::ConRevision.converge_solo(), "seguridad NO se resuelve por ultimo-gana");
}

#[test]
fn las_etiquetas_van_y_vuelven() {
    for t in [
        TipoHecho::Idempotente,
        TipoHecho::Conmutativo,
        TipoHecho::RecursoExclusivo,
        TipoHecho::ConRevision,
    ] {
        let e = t.etiqueta();
        let vuelta = TipoHecho::desde_etiqueta(e).expect("debe volver");
        assert_eq!(t, vuelta);
    }
    println!();
    println!("[{}] las 4 etiquetas van y vuelven", marca(true));
    assert!(TipoHecho::desde_etiqueta("inventado").is_none());
}
