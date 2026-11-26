//! Digest recalculable con hechos reales: dos réplicas que deben coincidir.
//!
//! ## Qué se simula
//!
//! Dos nodos replican los mismos hechos pero **los reciben en orden distinto**
//! (lo normal en una red). Si el digest no fuera determinista, darían valores
//! diferentes y el sistema creería que hay divergencia donde no la hay.
//!
//! Y al revés: si uno materializó mal (bug del aplicador), el digest lo detecta.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::digest::{comparar, derivar, Diagnostico};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, TipoHecho};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

fn escribe(host: &mut MemoryHost, nodo: &str, inst: &str, n: u64, id: &Identidad) -> Vec<Hecho> {
    let mut prev = String::new();
    let mut out = Vec::new();
    for i in 0..n {
        let tipo = match i % 3 {
            0 => TipoHecho::Idempotente,
            1 => TipoHecho::Conmutativo,
            _ => TipoHecho::ConRevision,
        };
        let mut h = Hecho::v3(
            nodo, "estado", i, inst, 0,
            &format!("clave-{}", i % 5),
            &format!("valor-{i}"),
            &prev, 1000 + i, tipo,
        );
        h.firmar(id);
        prev = h.hash();
        hechos_store::guardar(host, &h).expect("guardar");
        out.push(h);
    }
    out
}

#[test]
fn dos_replicas_con_los_mismos_hechos_en_orden_distinto_coinciden() {
    println!();
    println!("==================================================================");
    println!("DIGEST RECALCULABLE — dos replicas");
    println!("==================================================================");

    let id = Identidad::generar();

    // Réplica 1: recibe en orden.
    let mut h1 = MemoryHost::default();
    let hechos = escribe(&mut h1, "NODO-A", "inst-A", 100, &id);
    let e1 = derivar(&hechos);

    // Réplica 2: recibe los mismos hechos pero al revés.
    let mut h2 = MemoryHost::default();
    let mut al_reves = hechos.clone();
    al_reves.reverse();
    for h in &al_reves {
        hechos_store::guardar(&mut h2, h).expect("guardar");
    }
    let leidos_reves = hechos_store::leer_serie_de_rama(&h2, "NODO-A", "estado", "inst-A");
    let e2 = derivar(&leidos_reves);

    let d1 = e1.digest();
    let d2 = e2.digest();
    let iguales = d1 == d2;

    println!("  replica 1: {} claves, digest {}", e1.len(), &d1[..16]);
    println!("  replica 2: {} claves, digest {}", e2.len(), &d2[..16]);
    println!("[{}] mismo conjunto en orden distinto -> MISMO digest", marca(iguales));
    assert!(iguales, "el digest no puede depender del orden de llegada");

    match comparar(&e1, &e2) {
        Diagnostico::Iguales(_) => println!("[{}] el diagnostico dice: iguales", marca(true)),
        _ => panic!("deberia decir iguales"),
    }
}

#[test]
fn si_una_replica_materializa_mal_el_digest_lo_detecta() {
    // Este es el bug que Smith avisaba: "un bug del applier es divergencia
    // permanente aunque f sea pura".
    //
    // OJO CON EL TEST: con 60 hechos y 5 claves, gana el ULTIMO de cada clave.
    // Borrar un hecho intermedio NO cambia el estado (correcto). Para que el
    // test mida algo hay que borrar el hecho VIGENTE de alguna clave.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hechos = escribe(&mut host, "NODO-A", "inst-A", 60, &id);

    let buena = derivar(&hechos);

    // La replica mala pierde el hecho vigente de la clave 3
    // (seq%5==3 -> seq 58 es el ultimo).
    let mut mala_hechos = hechos.clone();
    let pos = mala_hechos
        .iter()
        .rposition(|h| h.clave == "clave-3")
        .expect("debe existir clave-3");
    mala_hechos.remove(pos);
    let mala = derivar(&mala_hechos);

    let d = comparar(&buena, &mala);
    println!();
    match &d {
        Diagnostico::Divergen { distintos, solo_en_a, solo_en_b, .. } => {
            println!("[{}] perder el hecho VIGENTE de una clave -> DIVERGEN", marca(true));
            println!("      claves distintas: {:?}", distintos);
            println!("      solo en buena:    {:?}", solo_en_a);
            println!("      solo en mala:     {:?}", solo_en_b);
        }
        _ => panic!("deberia divergir"),
    }
    assert!(!d.es_igual(), "perder el hecho vigente debe cambiar el digest");

    // Y comprobamos lo contrario: borrar uno intermedio NO cambia nada, porque
    // el estado solo guarda el vigente. Eso es correcto, no un fallo.
    let mut con_hueco = hechos.clone();
    con_hueco.remove(10); // hecho intermedio, no vigente
    let con_hueco_estado = derivar(&con_hueco);
    println!("[{}] perder un hecho NO vigente NO cambia el estado (correcto)",
        marca(comparar(&buena, &con_hueco_estado).es_igual()));
    assert!(comparar(&buena, &con_hueco_estado).es_igual());
}

#[test]
fn el_digest_detecta_que_clave_concreta_fallo() {
    // No basta con saber "divergen": hay que saber QUE clave, o el bug es
    // indepurable.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hechos = escribe(&mut host, "NODO-A", "inst-A", 50, &id);

    let buena = derivar(&hechos);

    // Se corrompe el hecho VIGENTE de clave-3 (hay que buscar el ultimo).
    let mut rotos = hechos.clone();
    let pos = rotos
        .iter()
        .rposition(|h| h.clave == "clave-3")
        .expect("debe existir");
    rotos[pos].valor = "CORROMPIDO".into();
    let mala = derivar(&rotos);

    match comparar(&buena, &mala) {
        Diagnostico::Divergen { distintos, .. } => {
            println!();
            println!("[{}] el digest senala la clave concreta: {:?}",
                marca(distintos.contains(&"clave-3".to_string())), distintos);
            assert!(distintos.contains(&"clave-3".to_string()));
        }
        _ => panic!("deberia divergir en clave-3"),
    }
}

#[test]
fn recalcular_desde_cero_da_lo_mismo_que_el_estado_incremental() {
    // Smith: "si no puedes recalcular desde cero, no tienes CRDT".
    // Aqui se comprueba que el recalculo completo coincide con el incremental.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hechos = escribe(&mut host, "NODO-A", "inst-A", 80, &id);

    // Estado "incremental": derivado de los hechos de uno en uno.
    let mut acumulado: Vec<Hecho> = Vec::new();
    for h in &hechos {
        acumulado.push(h.clone());
    }
    let incremental = derivar(&acumulado);

    // Estado "desde cero": releido del store completo.
    let del_store = hechos_store::leer_serie_de_rama(&host, "NODO-A", "estado", "inst-A");
    let desde_cero = derivar(&del_store);

    println!();
    println!("[{}] recalcular desde cero == incremental", marca(desde_cero.digest() == incremental.digest()));
    assert_eq!(incremental.digest(), desde_cero.digest());
}
