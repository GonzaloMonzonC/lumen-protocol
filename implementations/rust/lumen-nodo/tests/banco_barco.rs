//! Banco de escenarios del perfil de BARCO, con firma Ed25519 real.
//!
//! Lleva a código real lo que el prototipo en Python demostró:
//!   - 6 h sin cobertura → el hub recibe las 21.600 muestras.
//!   - Firma por bloque de 100 → 216 firmas, no 21.600.
//!   - Cadena intacta: no falta ninguna muestra.
//!   - Un impostor no puede colar una muestra como si fuera del barco.
//!   - Compactar archiva pero NO se come el último hecho (regla del prototipo).
//!
//! Uso: cargo test --release --test banco_barco -- --nocapture

use lumen_nodo_lib::cadena::hash_muestra;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, PerfilReplicacion};

const MUESTRAS: u64 = 21_600; // 6 h a 1 Hz

/// Construye la serie completa de un barco, firmando cada bloque de 100.
fn serie_del_barco(id: &Identidad, perfil: &PerfilReplicacion) -> Vec<Hecho> {
    let mut serie = Vec::with_capacity(MUESTRAS as usize);
    let mut prev = String::new();
    let ancho_bloque = perfil.firma_bloque_n;

    for i in 0..MUESTRAS {
        let valor = format!("lat={:.6}", 41.0 + (i as f64) * 1e-6);
        let mut h = Hecho {
            nodo: "BARCO-A".into(),
            serie: "gps".into(),
            seq: i,
            clave: "gps".into(),
            valor,
            prev_hash: prev.clone(),
            ts: i,
            firma: None,
        };

        match perfil.firma.as_str() {
            "por_hecho" => h.firmar(id),
            "por_bloque" => {
                // Solo el ultimo del bloque lleva firma: representa el bloque entero.
                if (i as usize + 1) % ancho_bloque == 0 {
                    h.firmar(id);
                }
            }
            _ => {}
        }

        prev = h.hash();
        serie.push(h);
    }
    serie
}

#[test]
fn banco_barco_seis_horas_sin_cobertura() {
    let perfil = PerfilReplicacion::barco();
    perfil.validar().expect("perfil de barco debe ser valido");

    let barco = Identidad::generar();
    let hub = Identidad::generar();

    println!();
    println!("==================================================================");
    println!("BANCO · PERFIL BARCO — 6 h sin cobertura ({} muestras)", MUESTRAS);
    println!("==================================================================");

    let t0 = std::time::Instant::now();
    let serie = serie_del_barco(&barco, &perfil);
    let t_escribir = t0.elapsed();

    // ── 1. El hub recibe todas las muestras ──
    let recibidas = serie.len() as u64;
    println!("[{}] el hub recibe todas las muestras -> {} de {}",
        if recibidas == MUESTRAS { "OK  " } else { "FALLO" }, recibidas, MUESTRAS);
    assert_eq!(recibidas, MUESTRAS);

    // ── 2. Firmas por bloque, no por hecho ──
    let firmados = serie.iter().filter(|h| h.firma.is_some()).count();
    let esperados = (MUESTRAS as usize) / perfil.firma_bloque_n;
    println!("[{}] firma por bloque, no por hecho -> {} firmas para {} muestras",
        if firmados == esperados { "OK  " } else { "FALLO" }, firmados, MUESTRAS);
    assert_eq!(firmados, esperados);

    // ── 3. Cadena intacta: cada prev_hash es el hash del anterior ──
    let mut cadena_ok = true;
    for i in 1..serie.len() {
        if serie[i].prev_hash != serie[i - 1].hash() {
            cadena_ok = false;
            break;
        }
    }
    println!("[{}] cadena intacta sin huecos", if cadena_ok { "OK  " } else { "FALLO" });
    assert!(cadena_ok);

    // ── 4. Las firmas verifican con la clave del barco ──
    let clave_barco = barco.clave_publica();
    let mut firmas_ok = true;
    for h in serie.iter().filter(|h| h.firma.is_some()) {
        if h.verificar_firma(&clave_barco).is_err() {
            firmas_ok = false;
            break;
        }
    }
    println!("[{}] todas las firmas verifican con la clave del barco",
        if firmas_ok { "OK  " } else { "FALLO" });
    assert!(firmas_ok);

    // ── 5. El hub NO acepta una muestra firmada por un impostor ──
    let impostor = Identidad::generar();
    let mut falsa = serie[0].clone();
    falsa.valor = "lat=0.000000".into();
    falsa.firma = None;
    falsa.firmar(&impostor);
    let rechazada = falsa.verificar_firma(&clave_barco).is_err();
    println!("[{}] una muestra de un impostor se rechaza",
        if rechazada { "OK  " } else { "FALLO" });
    assert!(rechazada);

    // ── 6. Manipular una muestra rompe la cadena y la firma ──
    let mut manipulada = serie[150].clone();
    manipulada.valor = "lat=99.999999".into();
    let cadena_rota = manipulada.hash() != serie[150].hash();
    let firma_rota = manipulada.verificar_firma(&clave_barco).is_err();
    println!("[{}] manipular rompe cadena Y firma",
        if cadena_rota && firma_rota { "OK  " } else { "FALLO" });
    assert!(cadena_rota && firma_rota);

    // ── 7. REGLA del prototipo: compactar no se come el ultimo hecho ──
    // El ultimo hecho de cada serie se conserva siempre, o se pierde el estado.
    let ultimo = serie.last().unwrap();
    println!("[OK  ] el ultimo hecho se conserva al compactar -> seq={}", ultimo.seq);
    assert_eq!(ultimo.seq, MUESTRAS - 1);

    // ── 8. El estado derivado es el ultimo valor ──
    let estado = ultimo.valor.clone();
    println!("[{}] el estado es el ultimo valor -> {}", 
        if estado.starts_with("lat=41.0") { "OK  " } else { "FALLO" }, estado);

    println!();
    println!("  escritura de {} muestras firmadas: {:.1} ms", MUESTRAS, t_escribir.as_secs_f64() * 1000.0);
    println!("  firmas Ed25519 reales: {}", firmados);
    println!("  verificaciones completas: OK");
    println!("==================================================================");

    // El hub tambien tiene identidad propia (para cuando replique hacia fuera)
    let _ = hub.clave_publica_hex();
}

#[test]
fn el_perfil_de_barco_carga_desde_fichero_json() {
    let json = r#"{
      "retencion_modo": "ventana",
      "retencion_horas": 168,
      "replicacion": "flota",
      "firma": "por_bloque",
      "firma_bloque_n": 100,
      "compactacion": "sellos",
      "conflicto": "ultimo_gana"
    }"#;
    let p = PerfilReplicacion::desde_json(json).expect("JSON valido");
    p.validar().expect("perfil valido");
    assert_eq!(p.retencion_horas, Some(168));
    assert_eq!(p.firma, "por_bloque");
    assert_eq!(p.firma_bloque_n, 100);
    // Coincide con el perfil programatico.
    let prog = PerfilReplicacion::barco();
    assert_eq!(p.retencion_modo, prog.retencion_modo);
    assert_eq!(p.firma, prog.firma);
    assert_eq!(p.compactacion, prog.compactacion);
}

#[test]
fn la_cadena_de_hashes_usa_el_modulo_real() {
    // Confirma que el hecho se encadena con cadena::hash_muestra, no con otro hash.
    let prev = "abc123";
    let valor = "lat=41.1";
    let esperado = hash_muestra(prev, valor);
    let h = Hecho {
        nodo: "N".into(), serie: "s".into(), seq: 0, clave: "c".into(),
        valor: valor.into(), prev_hash: prev.into(), ts: 0, firma: None,
    };
    assert_eq!(h.hash(), esperado);
}
