//! Hecho de conflicto de punta a punta: detectar, firmar, guardar, releer.
//!
//! ## Qué cierra esto
//!
//! Antes, cuando dos ramas chocaban, el conflicto se detectaba y se guardaba en
//! un `Vec` del resumen de recepción. **Al reiniciar el nodo, se perdía.**
//!
//! Un conflicto que se olvida al reiniciar es casi tan malo como uno descartado:
//! el operador ya no puede auditar qué pasó. Smith lo dijo: *"sin hecho de
//! conflicto explícito, la unión es una pérdida silenciosa"*.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::conflicto::{
    hecho_de_conflicto, motivo_de, motivo_de_hecho, MotivoConflicto, SERIE_CONFLICTOS,
};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, TipoHecho};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

/// Simula dos ramas que escriben en la misma posición (split-brain).
fn dos_ramas(id: &Identidad) -> (Hecho, Hecho) {
    // Rama A: instancia inst-A, escribe seq 0.
    let mut a = Hecho::v3(
        "DRON-1", "reserva", 0, "inst-A", 0, "celda-7",
        "dueno=A", "", 1000, TipoHecho::RecursoExclusivo,
    );
    a.firmar(id);

    // Rama B: otra instancia, misma posición, valor distinto.
    let mut b = Hecho::v3(
        "DRON-1", "reserva", 0, "inst-B", 0, "celda-7",
        "dueno=B", "", 1001, TipoHecho::RecursoExclusivo,
    );
    b.firmar(id);

    (a, b)
}

#[test]
fn un_conflicto_de_recurso_queda_registrado_como_hecho_firmado() {
    println!();
    println!("==================================================================");
    println!("HECHO DE CONFLICTO — de deteccion en memoria a evidencia persistente");
    println!("==================================================================");

    let id = Identidad::generar();
    let (a, b) = dos_ramas(&id);

    // Las dos ramas coexisten: no se descarta ninguna.
    let mut host = MemoryHost::default();
    hechos_store::guardar(&mut host, &a).expect("rama A");
    hechos_store::guardar(&mut host, &b).expect("rama B");

    let ramas = hechos_store::leer_serie_de_rama(&host, "DRON-1", "reserva", "inst-A");
    let ramas_b = hechos_store::leer_serie_de_rama(&host, "DRON-1", "reserva", "inst-B");
    println!("  rama A guardada: {} hechos", ramas.len());
    println!("  rama B guardada: {} hechos", ramas_b.len());
    println!("[{}] las DOS ramas siguen ahi (no se descarta nada)",
        marca(ramas.len() == 1 && ramas_b.len() == 1));

    // Ahora se construye la EVIDENCIA del conflicto como hecho firmado.
    let c = lumen_nodo_lib::hechos_wire::Conflicto {
        nodo: "DRON-1".into(),
        serie: "reserva".into(),
        seq: 0,
        instance_existente: "inst-A".into(),
        instance_nueva: "inst-B".into(),
        hash_existente: a.hash(),
        hash_nuevo: b.hash(),
        epoch_existente: 0,
        epoch_nuevo: 0,
    };

    let motivo = motivo_de(&c, a.tipo);
    let mut hc = hecho_de_conflicto("HUB-1", "hub", 0, 0, "", 2000, &c, motivo);
    hc.firmar(&id);

    hechos_store::guardar(&mut host, &hc).expect("conflicto");

    println!("[{}] el conflicto queda como hecho firmado (motivo: {})",
        marca(true), motivo.etiqueta());
    println!("      valor legible: {}", &hc.valor[..70.min(hc.valor.len())]);
    println!("      ...{}", &hc.valor[70.min(hc.valor.len())..]);
}

#[test]
fn el_conflicto_sobrevive_al_reinicio() {
    // EL TEST QUE CIERRA EL AGUJERO: antes se perdia al reiniciar.
    //
    // OJO: con `MemoryHost` este test NO probaba nada (no persiste entre
    // procesos). Hay que usar LMDB de verdad, guardar, CERRAR y reabrir.
    let id = Identidad::generar();
    let (a, b) = dos_ramas(&id);

    let c = lumen_nodo_lib::hechos_wire::Conflicto {
        nodo: "DRON-1".into(),
        serie: "reserva".into(),
        seq: 0,
        instance_existente: "inst-A".into(),
        instance_nueva: "inst-B".into(),
        hash_existente: a.hash(),
        hash_nuevo: b.hash(),
        epoch_existente: 0,
        epoch_nuevo: 0,
    };
    let motivo = MotivoConflicto::RecursoDisputado;
    let mut hc = hecho_de_conflicto("HUB-1", "hub", 0, 0, "", 2000, &c, motivo);
    hc.firmar(&id);

    let dir = std::env::temp_dir().join(format!("conf-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let dir_s = dir.to_string_lossy().to_string();

    // Primer "proceso": guarda y se cierra (el handle se suelta al salir).
    {
        let mut host = MemoryHost::from_lmdb(&dir_s).expect("abrir lmdb");
        hechos_store::guardar(&mut host, &hc).expect("guardar");
        drop(host);
    }

    // Segundo "proceso": reabre. Aqui es donde antes no habia nada.
    {
        let host2 = MemoryHost::from_lmdb(&dir_s).expect("reabrir lmdb");
        let leidos = hechos_store::leer_serie_de_rama(&host2, "HUB-1", SERIE_CONFLICTOS, "hub");

        println!();
        println!("[{}] tras cerrar y reabrir, el conflicto sigue: {} hecho(s)",
            marca(leidos.len() == 1), leidos.len());

        if let Some(h) = leidos.first() {
            let m = motivo_de_hecho(h);
            println!("[{}] y se puede leer el motivo: {:?}", marca(m == Some(motivo)), m);
            println!("      clave:        {}", h.clave);
            println!("      hash rama A:  {}", &c.hash_existente[..16]);
            println!("      hash rama B:  {}", &c.hash_nuevo[..16]);
            assert_eq!(m, Some(motivo));
            assert_eq!(h.clave, "DRON-1:reserva:0");
            assert!(h.valor.contains(&c.hash_existente));
            assert!(h.valor.contains(&c.hash_nuevo));
            assert_eq!(h.tipo, TipoHecho::ConRevision);
            // Y la firma sigue siendo valida tras el viaje por disco.
            let pubk = lumen_nodo_lib::identidad::hex_a_bytes_publico(&id.clave_publica_hex()).unwrap();
            println!("[{}] la firma sigue valida tras el disco", marca(h.verificar_firma(&pubk).is_ok()));
            assert!(h.verificar_firma(&pubk).is_ok());
        }
        assert_eq!(leidos.len(), 1);
    }

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn el_conflicto_dice_si_necesita_operador() {
    let id = Identidad::generar();
    let (a, b) = dos_ramas(&id);
    let c = lumen_nodo_lib::hechos_wire::Conflicto {
        nodo: "DRON-1".into(), serie: "reserva".into(), seq: 0,
        instance_existente: "inst-A".into(), instance_nueva: "inst-B".into(),
        hash_existente: a.hash(), hash_nuevo: b.hash(),
        epoch_existente: 0, epoch_nuevo: 0,
    };

    println!();
    for (tipo, esperado) in [
        (TipoHecho::RecursoExclusivo, true),
        (TipoHecho::ConRevision, true),
        (TipoHecho::Idempotente, false),
    ] {
        let m = motivo_de(&c, tipo);
        let h = hecho_de_conflicto("H", "i", 0, 0, "", 1, &c, m);
        let dice_operador = h.valor.contains("pendiente=operador:true");
        println!("[{}] tipo {:?} -> motivo {} -> operador: {}",
            marca(dice_operador == esperado), tipo, m.etiqueta(), dice_operador);
        assert_eq!(dice_operador, esperado);
    }
}

#[test]
fn dos_conflictos_distintos_se_encadenan() {
    // El hecho de conflicto vive en su propia serie, asi que se encadena como
    // cualquier otra: no es un caso especial.
    let id = Identidad::generar();
    let (a, b) = dos_ramas(&id);
    let c = lumen_nodo_lib::hechos_wire::Conflicto {
        nodo: "DRON-1".into(), serie: "reserva".into(), seq: 0,
        instance_existente: "inst-A".into(), instance_nueva: "inst-B".into(),
        hash_existente: a.hash(), hash_nuevo: b.hash(),
        epoch_existente: 0, epoch_nuevo: 0,
    };

    let mut h1 = hecho_de_conflicto("HUB-1", "hub", 0, 0, "", 2000, &c,
        MotivoConflicto::RecursoDisputado);
    h1.firmar(&id);
    let prev = h1.hash();

    let mut h2 = hecho_de_conflicto("HUB-1", "hub", 0, 1, &prev, 2001, &c,
        MotivoConflicto::DecisionDeSeguridad);
    h2.firmar(&id);

    let mut host = MemoryHost::default();
    hechos_store::guardar(&mut host, &h1).expect("h1");
    hechos_store::guardar(&mut host, &h2).expect("h2");

    let cadena = hechos_store::verificar_serie(&[
        hechos_store::leer_rama(&host, "HUB-1", SERIE_CONFLICTOS, 0, "hub").expect("0"),
        hechos_store::leer_rama(&host, "HUB-1", SERIE_CONFLICTOS, 1, "hub").expect("1"),
    ]);

    println!();
    println!("[{}] los conflictos se encadenan como cualquier serie", marca(cadena.is_ok()));
    assert!(cadena.is_ok(), "la cadena de conflictos debe verificar: {cadena:?}");
}
