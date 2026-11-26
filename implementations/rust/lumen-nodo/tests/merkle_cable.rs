//! Prueba de inclusión de punta a punta: se pide por el cable y se verifica.
//!
//! Cierra los dos agujeros que tenía Merkle al commitearlo:
//!  1. Solo se construía desde hashes sueltos, no desde una serie del store.
//!  2. No había forma de pedirla ni de recibirla por red.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::Hecho;

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

fn serie(host: &mut MemoryHost, nodo: &str, n: u64, id: &Identidad) {
    let mut prev = String::new();
    for i in 0..n {
        let mut h = Hecho::v2(
            nodo, "ledger", i, "inst-A", 0, "gps",
            &format!("saldo={i}"), &prev, i,
        );
        h.firmar(id);
        prev = h.hash();
        hechos_store::guardar(host, &h).expect("guardar");
    }
}

#[test]
fn pedir_una_prueba_por_el_cable_y_verificarla() {
    println!();
    println!("==================================================================");
    println!("MERKLE de punta a punta: peticion por el cable");
    println!("==================================================================");

    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    serie(&mut host, "NODO-1", 300, &id);

    // 1. El verificador pide la prueba del hecho 150.
    let peticion = hechos_wire::mensaje_peticion_prueba("ledger", 150);
    let (serie_pedida, seq_pedida) =
        hechos_wire::peticion_de_prueba(&peticion).expect("debe ser una peticion");
    println!("  peticion: serie={serie_pedida} seq={seq_pedida} ({} bytes)",
        peticion.body.len());

    // 2. El nodo la busca en el store y la devuelve.
    let prueba = hechos_store::prueba_de_hecho(&host, "NODO-1", &serie_pedida, "inst-A", seq_pedida)
        .expect("debe haber prueba");
    let respuesta = hechos_wire::mensaje_prueba(&prueba);
    println!("  respuesta: {} bytes ({} hashes en el camino)",
        respuesta.body.len(), prueba.camino.len());

    // 3. El verificador la reconstruye del cable y la comprueba.
    let recibida = hechos_wire::prueba_de_mensaje(&respuesta).expect("debe parsearse");
    let vale = recibida.verificar();

    println!("[{}] prueba recibida y verificada (raiz {})",
        marca(vale), &recibida.raiz[..16]);
    println!("  el verificador NO recibio los 300 hechos: solo {} hashes",
        recibida.camino.len());

    assert!(vale);
    assert_eq!(recibida.indice, 150);
    assert_eq!(recibida.total_hojas, 300);
}

#[test]
fn la_prueba_ocupa_mucho_menos_que_la_serie() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    serie(&mut host, "NODO-1", 5000, &id);

    let prueba = hechos_store::prueba_de_hecho(&host, "NODO-1", "ledger", "inst-A", 2500)
        .expect("prueba");
    let msg = hechos_wire::mensaje_prueba(&prueba);

    // Serializar la serie entera para comparar.
    let hechos = hechos_store::leer_serie_de_rama(&host, "NODO-1", "ledger", "inst-A");
    let serie_bytes: usize = hechos.iter().map(|h| hechos_store::a_texto(h).len()).sum();

    println!();
    println!("  5.000 hechos:");
    println!("    serie completa por el cable:  {} bytes", serie_bytes);
    println!("    prueba de inclusion:          {} bytes", msg.body.len());
    println!("    ahorro: {}x", serie_bytes / msg.body.len().max(1));

    assert!(prueba.verificar());
    assert!(msg.body.len() < serie_bytes / 100, "la prueba debe ser >100x menor");
}

#[test]
fn una_prueba_de_un_hecho_que_no_existe_no_se_genera() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    serie(&mut host, "NODO-1", 50, &id);

    println!();
    println!("[{}] seq 9999 no existe -> no hay prueba",
        marca(hechos_store::prueba_de_hecho(&host, "NODO-1", "ledger", "inst-A", 9999).is_none()));
    assert!(hechos_store::prueba_de_hecho(&host, "NODO-1", "ledger", "inst-A", 9999).is_none());

    println!("[{}] serie inexistente  -> no hay prueba",
        marca(hechos_store::prueba_de_hecho(&host, "NODO-1", "otra", "inst-A", 0).is_none()));
    assert!(hechos_store::prueba_de_hecho(&host, "NODO-1", "otra", "inst-A", 0).is_none());
}

#[test]
fn el_mensaje_de_prueba_va_y_vuelve_intacto() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    serie(&mut host, "NODO-1", 1000, &id);

    let original = hechos_store::prueba_de_hecho(&host, "NODO-1", "ledger", "inst-A", 777)
        .expect("prueba");
    let msg = hechos_wire::mensaje_prueba(&original);
    let vuelta = hechos_wire::prueba_de_mensaje(&msg).expect("parse");

    println!();
    println!("[{}] la prueba sobrevive al cable sin perder nada",
        marca(vuelta == original));
    assert_eq!(vuelta, original);
    assert!(vuelta.verificar());
}

#[test]
fn una_prueba_manipulada_en_el_cable_se_detecta() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    serie(&mut host, "NODO-1", 200, &id);

    let prueba = hechos_store::prueba_de_hecho(&host, "NODO-1", "ledger", "inst-A", 100)
        .expect("prueba");
    assert!(prueba.verificar(), "la prueba legitima debe valer");

    // Un intermediario cambia el hash de la hoja. Se manipula la ESTRUCTURA
    // (igual que haria un atacante que edita el cable), no el texto.
    let mut falsa = prueba.clone();
    falsa.hash_hoja = "f".repeat(64);
    let msg = hechos_wire::mensaje_prueba(&falsa);
    let recibida = hechos_wire::prueba_de_mensaje(&msg).expect("parse");

    println!();
    println!("[{}] una prueba con la hoja cambiada NO verifica",
        marca(!recibida.verificar()));
    assert!(!recibida.verificar(), "cambiar el hecho debe romper la prueba");

    // Y si cambia un hermano del camino, tampoco.
    let mut falsa2 = prueba.clone();
    if !falsa2.camino.is_empty() {
        falsa2.camino[0].0 = "e".repeat(64);
        let msg2 = hechos_wire::mensaje_prueba(&falsa2);
        let r2 = hechos_wire::prueba_de_mensaje(&msg2).expect("parse");
        println!("[{}] una prueba con un hermano cambiado tampoco",
            marca(!r2.verificar()));
        assert!(!r2.verificar());
    }
}

