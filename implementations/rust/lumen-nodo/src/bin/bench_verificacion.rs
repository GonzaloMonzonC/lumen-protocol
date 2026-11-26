//! Coste de VERIFICAR una serie grande — el cuello real de un ledger.
//!
//! ## Por qué se mide esto
//!
//! Un hub que recibe 21.600 hechos de un barco no solo los guarda: los
//! **verifica**. Cada hecho con firma es una verificación Ed25519, que no es
//! gratis (curva elíptica).
//!
//! Si verificar 21.600 hechos tarda segundos, un ledger con millones de hechos
//! es inviable y hay que cambiar la estrategia (firma por lote, verificación
//! diferida, Merkle agregado...).
//!
//! Uso: bench_verificacion <n>

use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::Hecho;

fn ahora() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_micros())
        .unwrap_or(0)
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let n: u64 = if a.len() > 1 { a[1].parse().expect("n") } else { 21600 };

    let id = Identidad::generar();
    let pubk = id.clave_publica();

    // 1. Serie A: firmada POR HECHO (el caso caro, el que verifica cada firma).
    let t0 = ahora();
    let mut serie: Vec<Hecho> = Vec::with_capacity(n as usize);
    let mut prev = String::new();
    for i in 0..n {
        let mut h = Hecho::v2(
            "BARCO-A", "gps", i, "inst-A", 0, "gps",
            &format!("lat=41.{i}"), &prev, i,
        );
        h.firmar(&id);
        prev = h.hash();
        serie.push(h);
    }
    let t_firmar = ahora().saturating_sub(t0);
    println!("firmar por hecho n={n} -> {:.1} ms ({:.1} us/hecho)",
        t_firmar as f64 / 1000.0, t_firmar as f64 / n as f64);

    // 1b. Serie B: firmada POR BLOQUE de 100 — el perfil de barco.
    // Solo la ultima muestra de cada bloque lleva firma, y firma el SELLO.
    const BLOQUE: usize = 100;
    let t0 = ahora();
    let mut serie_bloque: Vec<Hecho> = Vec::with_capacity(n as usize);
    let mut prev = String::new();
    for i in 0..n {
        let h = Hecho::v2(
            "BARCO-B", "gps", i, "inst-B", 0, "gps",
            &format!("lat=41.{i}"), &prev, i,
        );
        prev = h.hash();
        serie_bloque.push(h);
    }
    // Firmar el sello de cada bloque completo.
    // Ya existe `firmar_bloque` en hechos_wire: usarla, no reimplementarla.
    let sellos_firmados = lumen_nodo_lib::hechos_wire::firmar_bloque(
        &mut serie_bloque, BLOQUE, &id);

    let t_firmar_bloque = ahora().saturating_sub(t0);
    println!("firmar por bloque n={n} -> {:.1} ms ({} sellos)",
        t_firmar_bloque as f64 / 1000.0, sellos_firmados);

    // 2. Verificar TODAS las firmas (lo que hace verificar_serie_con_firmas).
    let t0 = ahora();
    let mut ok = 0usize;
    for h in serie.iter().filter(|h| h.firma.is_some()) {
        h.verificar_firma(&pubk).expect("debe verificar");
        ok += 1;
    }
    let t_ver = ahora().saturating_sub(t0);
    println!("verificar n={n} -> {:.1} ms ({:.1} us/hecho)  [{} firmas]",
        t_ver as f64 / 1000.0, t_ver as f64 / n as f64, ok);


    // 3b. Verificar SOLO los sellos de bloque (el camino que usa el perfil de
    // barco). Es el que de verdad se usa en produccion; el de arriba verifica
    // cada firma individual, que con firma por bloque NO es lo que hay.
    let t0 = ahora();
    let sellos = lumen_nodo_lib::hechos_wire::verificar_solo_bloques(&serie_bloque, 100, &pubk)
        .expect("sellos");
    let t_sellos = ahora().saturating_sub(t0);
    println!("solo sellos n={n} -> {:.1} ms ({:.2} us/hecho)  [{} sellos]",
        t_sellos as f64 / 1000.0, t_sellos as f64 / n as f64, sellos);

    // 3c. Los dos caminos juntos: cadena + sellos (lo que hace verificar_bloques).
    let t0 = ahora();
    lumen_nodo_lib::hechos_wire::verificar_bloques(&serie_bloque, 100, &pubk).expect("bloques");
    let t_bloques = ahora().saturating_sub(t0);
    println!("cadena+sellos n={n} -> {:.1} ms ({:.2} us/hecho)",
        t_bloques as f64 / 1000.0, t_bloques as f64 / n as f64);

    // 3. Verificar solo la cadena de hashes (sin criptografia).
    let t0 = ahora();
    lumen_nodo_lib::hechos_store::verificar_serie(&serie).expect("cadena");
    let t_cad = ahora().saturating_sub(t0);
    println!("solo cadena n={n} -> {:.1} ms ({:.2} us/hecho)",
        t_cad as f64 / 1000.0, t_cad as f64 / n as f64);


    // ── 5. Muchas series en PARALELO (el caso del ledger) ──
    //
    // Cada cuenta/usuario es una serie independiente. La cadena es secuencial
    // dentro de una serie, pero series distintas se verifican a la vez.
    println!();
    println!("PARALELISMO — {} nucleos", std::thread::available_parallelism()
        .map(|n| n.get()).unwrap_or(0));

    let n_series = 100u64;          // 100 cuentas
    let por_serie = 200u64;         // 200 hechos cada una
    let mut series: Vec<(String, Vec<Hecho>)> = Vec::new();
    for serie_i in 0..n_series {
        let mut v = Vec::with_capacity(por_serie as usize);
        let mut prev = String::new();
        for i in 0..por_serie {
            let mut h = Hecho::v2(
                "LEDGER", "cuenta", i, &format!("cuenta-{serie_i}"), 0,
                &format!("cuenta:{serie_i}"), &format!("tx={i}"), &prev, i,
            );
            h.firmar(&id);
            prev = h.hash();
            v.push(h);
        }
        series.push((format!("cuenta-{serie_i}"), v));
    }
    let total_hechos = n_series * por_serie;

    // Secuencial
    let t0 = ahora();
    for (_n, v) in &series {
        lumen_nodo_lib::hechos_store::verificar_serie_con_firmas(v, &pubk)
            .expect("verificar secuencial");
    }
    let t_seq = ahora().saturating_sub(t0);

    // En paralelo
    let series2: Vec<(String, Vec<Hecho>)> = series
        .iter()
        .map(|(n, v)| (n.clone(), v.clone()))
        .collect();
    let t0 = ahora();
    let res = lumen_nodo_lib::hechos_store::verificar_series_en_paralelo(
        series2,
        |v| lumen_nodo_lib::hechos_store::verificar_serie_con_firmas(v, &pubk).map(|_| ()),
    );
    let t_par = ahora().saturating_sub(t0);

    let ok = res.iter().filter(|(_, r)| r.is_ok()).count();
    println!("  {n_series} series x {por_serie} = {total_hechos} hechos");
    println!("  secuencial -> {:>7.0} ms", t_seq as f64 / 1000.0);
    println!("  paralelo   -> {:>7.0} ms   ({:.1}x)", t_par as f64 / 1000.0,
        t_seq as f64 / t_par.max(1) as f64);
    println!("  series verificadas OK: {ok}/{n_series}");

    // 4. Cuanto costaria un hub con millones de hechos.
    println!();
    let por_firma_us = t_ver as f64 / n as f64;
    let por_bloque_us = t_bloques as f64 / n as f64;
    println!("  {:<19} {:>12} {:>12}", "hechos", "todas firmas", "cadena+sellos");
    for total in [21_600u64, 240_000, 1_000_000, 10_000_000] {
        let a = por_firma_us * total as f64 / 1e6;
        let b = por_bloque_us * total as f64 / 1e6;
        println!("  {total:>10} hechos -> {a:>8.1} s   {b:>8.1} s  ({}x mas rapido)",
            if b > 0.0 { (a / b).round() as u64 } else { 0 });
    }
}
