//! Cierre: cuarentena persistida y digest cableado.
//!
//! Los dos últimos huecos del diseño de reconvergencia.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::cota_epoch::{
    persistir_evento, reconstruir, AccionCuarentena, Cota, Cuarentena, SERIE_CUARENTENA,
};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire::{
    comparar_digest, digest_de_rama, recibir_hechos_con_cota,
};
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, TipoHecho};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

fn msg(h: &Hecho) -> lumen_znet::DdpMessage {
    lumen_nodo_lib::hechos_wire::mensaje_de_hecho(h)
}

#[test]
fn la_cuarentena_sobrevive_al_reinicio() {
    println!();
    println!("==================================================================");
    println!("CIERRE — cuarentena persistida y digest en uso");
    println!("==================================================================");

    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    // Se aparta una rama por salto de epoch imposible.
    let v = Cota::default().revisar(0, 9999);
    let motivo = v.motivo();
    let seq = persistir_evento(
        &mut host, "HUB-1", "hub", 0, 1000,
        "inst-mala", AccionCuarentena::Apartar, &motivo, Some(&id),
    ).expect("persistir");

    println!("  evento de cuarentena guardado en seq {seq}");

    // Antes: esto se perdia al reiniciar. Ahora se reconstruye.
    let q = reconstruir(&host, "HUB-1", "hub");
    println!("[{}] tras 'reiniciar', la rama sigue apartada", marca(q.esta_apartada("inst-mala")));
    println!("      motivo: {}...", &q.motivo("inst-mala").unwrap()[..50.min(q.motivo("inst-mala").unwrap().len())]);
    assert!(q.esta_apartada("inst-mala"));
    assert_eq!(q.len(), 1);
}

#[test]
fn liberar_tambien_se_persiste() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    persistir_evento(&mut host, "HUB-1", "hub", 0, 1000, "inst-x",
        AccionCuarentena::Apartar, "salto raro", Some(&id)).expect("apartar");
    assert!(reconstruir(&host, "HUB-1", "hub").esta_apartada("inst-x"));

    persistir_evento(&mut host, "HUB-1", "hub", 0, 1001, "inst-x",
        AccionCuarentena::Liberar, "revisado por operador", Some(&id)).expect("liberar");

    let q = reconstruir(&host, "HUB-1", "hub");
    println!();
    println!("[{}] tras liberar, la rama vuelve a operar", marca(!q.esta_apartada("inst-x")));
    println!("[{}] y la cuarentena queda vacia", marca(q.esta_vacia()));
    assert!(!q.esta_apartada("inst-x"));
    assert!(q.esta_vacia());
}

#[test]
fn la_serie_de_cuarentena_se_encadena() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    for i in 0..5 {
        persistir_evento(&mut host, "HUB-1", "hub", 0, 1000 + i,
            &format!("inst-{i}"), AccionCuarentena::Apartar, "motivo", Some(&id))
            .expect("persistir");
    }

    let eventos = hechos_store::leer_serie_de_rama(&host, "HUB-1", SERIE_CUARENTENA, "hub");
    let ok = hechos_store::verificar_serie(&eventos).is_ok();
    println!();
    println!("[{}] {} eventos de cuarentena encadenados y verificados",
        marca(ok && eventos.len() == 5), eventos.len());
    assert!(ok);
    assert_eq!(eventos.len(), 5);
}

#[test]
fn el_digest_en_uso_detecta_divergencia() {
    // El digest ya no vive solo en tests: dos nodos lo calculan y comparan.
    let id = Identidad::generar();

    // Nodo A: recibe 10 hechos.
    let mut a = MemoryHost::default();
    let mut prev = String::new();
    for i in 0..10u64 {
        let mut h = Hecho::v3("DRON-1", "gps", i, "inst-A", 0, "gps",
            &format!("lat={i}"), &prev, 100 + i, TipoHecho::Idempotente);
        h.firmar(&id);
        prev = h.hash();
        recibir_hechos_con_cota(&mut a, &[msg(&h)], None, false, None);
    }

    // Nodo B: recibe 9 (le falta el último).
    let mut b = MemoryHost::default();
    let mut prev2 = String::new();
    for i in 0..9u64 {
        let mut h = Hecho::v3("DRON-1", "gps", i, "inst-A", 0, "gps",
            &format!("lat={i}"), &prev2, 100 + i, TipoHecho::Idempotente);
        h.firmar(&id);
        prev2 = h.hash();
        recibir_hechos_con_cota(&mut b, &[msg(&h)], None, false, None);
    }

    let (da, na) = digest_de_rama(&a, "DRON-1", "gps", "inst-A");
    let (db, nb) = digest_de_rama(&b, "DRON-1", "gps", "inst-A");

    println!();
    println!("  nodo A: {} claves, digest {}", na, &da[..16]);
    println!("  nodo B: {} claves, digest {}", nb, &db[..16]);
    println!("[{}] digests distintos -> divergencia", marca(da != db));
    assert_ne!(da, db);

    // A compara con el digest de B: debe avisar.
    let d = comparar_digest(&a, "DRON-1", "gps", "inst-A", &db);
    println!("[{}] comparar_digest avisa de la divergencia", marca(d.is_some()));
    assert!(d.is_some());

    // Y si compara consigo mismo, no dice nada.
    let igual = comparar_digest(&a, "DRON-1", "gps", "inst-A", &da);
    println!("[{}] comparar consigo mismo no da falso positivo", marca(igual.is_none()));
    assert!(igual.is_none());
}

#[test]
fn dos_nodos_con_los_mismos_hechos_coinciden_en_el_digest() {
    // ## La trampa de este test
    //
    // Lo primero que escribi metia los hechos AL REVES en el nodo B y esperaba
    // que coincidieran. FALLA, y esta bien que falle: al recibir el hecho 19 sin
    // el 18, la cadena lo RECHAZA ("falta seq 18"). Es correcto — no se puede
    // aceptar un hecho sin su predecesor.
    //
    // Asi que B no tenia los mismos hechos que A, y comparar sus digests no
    // probaba nada del digest: probaba que la cadena los habia rechazado.
    //
    // Lo que SI prueba el digest: dos nodos con el MISMO conjunto de hechos dan
    // el mismo digest, sin importar en que orden los METIO en el store (que es
    // otra cosa que el orden de recepcion).
    let id = Identidad::generar();

    let mut hechos = Vec::new();
    let mut prev = String::new();
    for i in 0..20u64 {
        let mut h = Hecho::v3("DRON-1", "gps", i, "inst-A", 0, "gps",
            &format!("lat={i}"), &prev, 100 + i, TipoHecho::Idempotente);
        h.firmar(&id);
        prev = h.hash();
        hechos.push(h);
    }

    // Los dos nodos reciben en orden (la cadena lo exige), pero luego se
    // comprueba que el DIGEST no depende de como esten ordenados en el vector
    // que se le pasa a derivar.
    let mut a = MemoryHost::default();
    for h in &hechos {
        recibir_hechos_con_cota(&mut a, &[msg(h)], None, false, None);
    }
    let mut b = MemoryHost::default();
    for h in &hechos {
        recibir_hechos_con_cota(&mut b, &[msg(h)], None, false, None);
    }

    let (da, na) = digest_de_rama(&a, "DRON-1", "gps", "inst-A");
    let (db, nb) = digest_de_rama(&b, "DRON-1", "gps", "inst-A");

    println!();
    // 20 hechos pero UNA sola clave ("gps"): el estado guarda el ultimo valor
    // de cada clave, asi que 1 clave es lo CORRECTO, no un fallo.
    println!("  nodo A: {} claves, nodo B: {} claves (20 hechos, 1 clave)", na, nb);
    println!("[{}] mismo conjunto -> mismo digest", marca(da == db && na == 1));
    assert_eq!(da, db);
    assert_eq!(na, 1, "20 hechos de la misma clave -> 1 clave en el estado");

    // Y el modulo del digest, por separado, SI es independiente del orden del
    // vector (eso ya se prueba en digest::tests). Aqui se confirma con hechos
    // reales del store, reordenando el vector en memoria.
    let del_store = hechos_store::leer_serie_de_rama(&a, "DRON-1", "gps", "inst-A");
    let mut al_reves = del_store.clone();
    al_reves.reverse();
    let d1 = lumen_nodo_lib::digest::derivar(&del_store).digest();
    let d2 = lumen_nodo_lib::digest::derivar(&al_reves).digest();
    println!("[{}] y derivar no depende del orden del vector", marca(d1 == d2));
    assert_eq!(d1, d2);
}

#[test]
fn la_cadena_rechaza_hechos_fuera_de_orden() {
    // Este es el comportamiento CORRECTO que mi test anterior confundia con un bug.
    // Un hecho que llega sin su predecesor se rechaza: no se puede verificar su
    // cadena sin el anterior.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    let mut prev = String::new();
    let mut hechos = Vec::new();
    for i in 0..3u64 {
        let mut h = Hecho::v3("DRON-1", "gps", i, "inst-A", 0, "gps",
            &format!("lat={i}"), &prev, 100 + i, TipoHecho::Idempotente);
        h.firmar(&id);
        prev = h.hash();
        hechos.push(h);
    }

    // Mandar el 2 primero: debe rechazarse.
    let r = recibir_hechos_con_cota(&mut host, &[msg(&hechos[2])], None, false, None);
    println!();
    println!("[{}] un hecho sin su predecesor se RECHAZA (correcto)",
        marca(r.rechazados == 1));
    println!("      motivo: {:?}", r.primer_motivo.as_deref());
    assert_eq!(r.rechazados, 1);
    assert_eq!(r.aceptados, 0);

    // Y en orden, entran los tres.
    for h in &hechos {
        recibir_hechos_con_cota(&mut host, &[msg(h)], None, false, None);
    }
    let guardados = hechos_store::leer_serie_de_rama(&host, "DRON-1", "gps", "inst-A");
    println!("[{}] en orden, entran los 3", marca(guardados.len() == 3));
    assert_eq!(guardados.len(), 3);
}
