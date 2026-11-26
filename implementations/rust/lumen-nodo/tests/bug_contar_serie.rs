//! El bug de `contar_serie` / `leer_serie`, cerrado de raíz.
//!
//! ## Qué pasaba
//!
//! Las dos miraban solo la rama **principal** (instancia `""`). Los hechos que
//! llegan de un nodo con identidad van en SU instancia (`inst-A`, `hub`, ...), así
//! que devolvían **0** y el llamante concluía "no hay hechos".
//!
//! **No daba error.** Devolvía un número plausible. Falló tres veces:
//!
//! 1. En `persistir_conflictos`: todos los conflictos se escribían en `seq 0` y
//!    se sobrescribían. 5 conflictos, 1 guardado.
//! 2. En `persistir_evento` (cuarentena): igual.
//! 3. Al leer series para la reconvergencia: el hub no encontraba nada que dar.

use lumen_mlight::MemoryHost;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, TipoHecho};

fn marca(ok: bool) -> &'static str {
    if ok { "OK  " } else { "FALLO" }
}

fn hecho_mayusculas(id: &Identidad, inst: &str, seq: u64, prev: &str) -> Hecho {
    let mut h = Hecho::v3(
        "DRON-1", "gps", seq, inst, 0, "gps",
        &format!("lat={seq}"), prev, 100 + seq, TipoHecho::Idempotente,
    );
    h.firmar(id);
    h
}

#[test]
fn contar_serie_cuenta_hechos_de_una_instancia_con_identidad() {
    // EL BUG: esto devolvia 0.
    println!();
    println!("==================================================================");
    println!("BUG DE contar_serie / leer_serie — cerrado de raiz");
    println!("==================================================================");

    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    let mut prev = String::new();
    for i in 0..10u64 {
        let h = hecho_mayusculas(&id, "inst-A", i, &prev);
        prev = h.hash();
        hechos_store::guardar(&mut host, &h).expect("guardar");
    }

    let n = hechos_store::contar_serie(&host, "DRON-1", "gps");
    println!("  10 hechos en instancia 'inst-A' -> contar_serie = {n}");
    println!("[{}] cuenta los hechos de una instancia con identidad", marca(n == 10));
    assert_eq!(n, 10, "antes devolvia 0 y el llamante creia que no habia nada");
}

#[test]
fn leer_serie_devuelve_los_hechos_de_una_instancia_con_identidad() {
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    let mut prev = String::new();
    for i in 0..10u64 {
        let h = hecho_mayusculas(&id, "inst-A", i, &prev);
        prev = h.hash();
        hechos_store::guardar(&mut host, &h).expect("guardar");
    }

    let serie = hechos_store::leer_serie(&host, "DRON-1", "gps");
    println!();
    println!("[{}] leer_serie devuelve los 10 (antes: vacio)", marca(serie.len() == 10));
    assert_eq!(serie.len(), 10);

    // Y la cadena sigue intacta: no se ha reordenado ni corrompido.
    let ok = hechos_store::verificar_serie(&serie).is_ok();
    println!("[{}] y la cadena verifica", marca(ok));
    assert!(ok);
}

#[test]
fn la_rama_principal_sigue_funcionando() {
    // No se puede romper el caso de siempre: hechos sin instancia.
    let mut host = MemoryHost::default();
    let mut prev = String::new();
    for i in 0..5u64 {
        let h = Hecho::v2("BARCO-A", "gps", i, "", 0, "gps", &format!("lat={i}"), &prev, i);
        prev = h.hash();
        hechos_store::guardar(&mut host, &h).expect("guardar");
    }

    let n = hechos_store::contar_serie(&host, "BARCO-A", "gps");
    let serie = hechos_store::leer_serie(&host, "BARCO-A", "gps");

    println!();
    println!("[{}] la rama principal (instancia '') sigue contando bien",
        marca(n == 5 && serie.len() == 5));
    assert_eq!(n, 5);
    assert_eq!(serie.len(), 5);
}

#[test]
fn varias_instancias_a_la_vez() {
    // Dos ramas del mismo nodo (split-brain): contar_serie cuenta posiciones, y
    // leer_serie devuelve una por posición.
    let id = Identidad::generar();
    let mut host = MemoryHost::default();

    for inst in ["inst-A", "inst-B"] {
        let mut prev = String::new();
        for i in 0..4u64 {
            let h = hecho_mayusculas(&id, inst, i, &prev);
            prev = h.hash();
            hechos_store::guardar(&mut host, &h).expect("guardar");
        }
    }

    let n = hechos_store::contar_serie(&host, "DRON-1", "gps");
    let serie = hechos_store::leer_serie(&host, "DRON-1", "gps");
    let todas = hechos_store::leer_todas_las_ramas(&host, "DRON-1", "gps");

    println!();
    println!("  dos ramas de 4 hechos: contar={n} leer_serie={} todas_las_ramas={}",
        serie.len(), todas.len());
    println!("[{}] contar_serie cuenta POSICIONES (4), no hechos totales (8)", marca(n == 4));
    println!("[{}] leer_serie da una por posicion", marca(serie.len() == 4));
    println!("[{}] leer_todas_las_ramas da las dos ramas (8)", marca(todas.len() == 8));
    assert_eq!(n, 4);
    assert_eq!(serie.len(), 4);
    assert_eq!(todas.len(), 8, "para split-brain hacen falta TODAS las ramas");
}

#[test]
fn la_serie_vacia_sigue_dando_cero() {
    let host = MemoryHost::default();
    println!();
    println!("[{}] una serie que no existe sigue dando 0 (no un falso positivo)",
        marca(hechos_store::contar_serie(&host, "NADIE", "nada") == 0));
    assert_eq!(hechos_store::contar_serie(&host, "NADIE", "nada"), 0);
    assert!(hechos_store::leer_serie(&host, "NADIE", "nada").is_empty());
}
