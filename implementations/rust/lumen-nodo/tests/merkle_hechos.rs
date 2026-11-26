//! Prueba de inclusión con HECHOS REALES de una serie.
//!
//! Los tests del módulo usan hashes inventados. Esto comprueba que funciona con
//! la estructura de verdad: hechos firmados, encadenados, en el store.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::merkle::ArbolMerkle;
use lumen_nodo_lib::replicacion::Hecho;

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

/// Escribe una serie de `n` hechos firmados y devuelve sus hashes en orden.
fn serie_firmada(host: &mut MemoryHost, nodo: &str, n: u64, id: &Identidad) -> Vec<String> {
    let mut prev = String::new();
    let mut hashes = Vec::with_capacity(n as usize);
    for i in 0..n {
        let mut h = Hecho::v2(
            nodo, "ledger", i, "inst-A", 0, "gps",
            &format!("hecho={i}"), &prev, i,
        );
        h.firmar(id);
        prev = h.hash();
        hashes.push(prev.clone());
        hechos_store::guardar(host, &h).expect("guardar");
    }
    hashes
}

#[test]
fn prueba_de_inclusion_sobre_hechos_reales() {
    println!();
    println!("==================================================================");
    println!("MERKLE SOBRE HECHOS REALES");
    println!("==================================================================");

    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hashes = serie_firmada(&mut host, "NODO-1", 500, &id);

    let arbol = ArbolMerkle::nuevo(&hashes);
    println!("  500 hechos -> raiz {}", &arbol.raiz()[..16]);

    // Todas las pruebas verifican.
    let mut ok = 0;
    for i in 0..hashes.len() {
        let p = arbol.prueba(i).expect("prueba");
        if p.verificar() {
            ok += 1;
        }
    }
    println!("[{}] las 500 pruebas verifican contra la raiz ({ok}/500)", marca(ok == 500));
    assert_eq!(ok, 500);
}

#[test]
fn demostrar_un_hecho_sin_entregar_los_21600() {
    // EL CASO REAL: un barco con 6 h de telemetria. Para probar que el hecho
    // 12.345 esta en el registro NO hace falta entregar los 21.600.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hashes = serie_firmada(&mut host, "BARCO", 21_600, &id);

    let t0 = std::time::Instant::now();
    let arbol = ArbolMerkle::nuevo(&hashes);
    let t_arbol = t0.elapsed();

    let p = arbol.prueba(12_345).expect("prueba");
    let t_prueba = t0.elapsed() - t_arbol;

    let serie_completa = hashes.iter().map(|h| h.len()).sum::<usize>();
    println!();
    println!("  21.600 hechos:");
    println!("    arbol construido en     {:?}", t_arbol);
    println!("    prueba generada en      {:?}", t_prueba);
    println!("    prueba: {} hashes = {} bytes", p.camino.len(), p.bytes());
    println!("    serie completa seria {} bytes", serie_completa);
    println!("    ahorro: {}x", serie_completa / p.bytes().max(1));

    let t0 = std::time::Instant::now();
    let vale = p.verificar();
    let t_ver = t0.elapsed();

    println!("[{}] la prueba verifica en {:?}", marca(vale), t_ver);
    assert!(vale);
    assert!(p.bytes() < 1200, "la prueba debe caber en un mensaje");
}

#[test]
fn un_hecho_manipulado_no_se_puede_probar() {
    // El atacante cambia un hecho y quiere demostrar que esta en el registro.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hashes = serie_firmada(&mut host, "NODO-1", 100, &id);
    let arbol = ArbolMerkle::nuevo(&hashes);

    let mut p = arbol.prueba(42).expect("prueba");
    assert!(p.verificar(), "la prueba legitima debe valer");

    // Ahora miente sobre el contenido.
    p.hash_hoja = lumen_nodo_lib::cadena::sha256_hex(b"hecho falso");

    println!();
    println!("[{}] un hecho manipulado NO puede probarse contra la raiz",
        marca(!p.verificar()));
    assert!(!p.verificar());
}

#[test]
fn borrar_un_hecho_del_medio_cambia_la_raiz() {
    // Si alguien borra un hecho, la raiz cambia: el registro entero se delata.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();
    let hashes = serie_firmada(&mut host, "NODO-1", 100, &id);

    let con_todos = ArbolMerkle::nuevo(&hashes).raiz();

    let mut sin_uno = hashes.clone();
    sin_uno.remove(50);
    let sin_el_50 = ArbolMerkle::nuevo(&sin_uno).raiz();

    println!();
    println!("[{}] borrar el hecho 50 cambia la raiz", marca(con_todos != sin_el_50));
    println!("    con todos:    {}", &con_todos[..16]);
    println!("    sin el 50:    {}", &sin_el_50[..16]);
    assert_ne!(con_todos, sin_el_50);

    // Y la prueba del hecho 60 (posterior) tampoco vale contra la raiz original.
    let arbol_sin = ArbolMerkle::nuevo(&sin_uno);
    let mut p = arbol_sin.prueba(59).expect("prueba"); // era el 60
    p.raiz = con_todos.clone();
    println!("[{}] la prueba de un hecho posterior no vale contra la raiz original",
        marca(!p.verificar()));
    assert!(!p.verificar());
}
