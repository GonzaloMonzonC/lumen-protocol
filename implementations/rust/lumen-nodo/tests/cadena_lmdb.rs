//! Prueba END-TO-END de `sign=hash-chain` sobre un LMDB real.
//!
//! Este test es el que demuestra que la cadena sirve para algo:
//!   1. escribe N muestras encadenadas en un entorno LMDB real
//!   2. verifica: íntegra
//!   3. BORRA una muestra del medio (como haría alguien manipulando la base)
//!   4. verifica otra vez: debe decir EXACTAMENTE cuál falta
//!
//! Sin el paso 3-4, la cadena sería decorativa.

#![cfg(feature = "motor-lmdb")]

use lumen_mlight::{Host, MemoryHost, Subscript};

use lumen_nodo_lib::cadena;

fn subs(n: u64) -> Vec<Subscript> {
    vec![
        Subscript::String("BARCO".into()),
        Subscript::String("lat".into()),
        Subscript::Number(n as f64),
    ]
}

/// Lee todas las muestras de la serie del host.
fn leer_serie(host: &MemoryHost, hasta: u64) -> Vec<(u64, String)> {
    let mut out = Vec::new();
    for n in 1..=hasta {
        if let Ok(Some(v)) = host.get("FLOTA", &subs(n)) {
            out.push((n, v.as_string()));
        }
    }
    out
}

#[test]
fn cadena_real_en_lmdb_detecta_una_muestra_borrada() {
    let dir = std::env::temp_dir().join(format!("lumen-nodo-e2e-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let dir_s = dir.to_string_lossy().to_string();

    let mut host = MemoryHost::from_lmdb(&dir_s).expect("abrir lmdb");

    // ── 1. Escribir 8 muestras encadenadas ────────────────────────
    let mut prev = String::new();
    for n in 1..=8u64 {
        let m = cadena::encadenar(&prev, &format!("4{n}.0")).expect("encadenar");
        prev = m.hash.clone();
        host.set("FLOTA", &subs(n), lumen_mlight::Value::String(m.a_texto()))
            .expect("set");
    }

    let muestras = leer_serie(&host, 10);
    assert_eq!(muestras.len(), 8, "deben estar las 8");

    // ── 2. Verificar: íntegra ─────────────────────────────────────
    let v = cadena::verificar(&muestras);
    assert!(v.es_integro(), "debe ser integra: {:?}", v.problema);
    assert_eq!(v.muestras_ok, 8);

    // ── 3. BORRAR la muestra 5 (manipulación) ─────────────────────
    let borradas = host.kill("FLOTA", &subs(5)).expect("kill");
    assert!(borradas >= 1, "debe haber borrado algo");

    let muestras = leer_serie(&host, 10);
    assert_eq!(muestras.len(), 7, "ahora deben quedar 7");

    // ── 4. Verificar: debe LOCALIZAR el hueco ─────────────────────
    let v = cadena::verificar(&muestras);
    assert!(!v.es_integro(), "UNA MUESTRA BORRADA DEBE DETECTARSE");
    match v.problema {
        Some(cadena::ErrorCadena::Hueco {
            falta,
            antes,
            despues,
        }) => {
            assert_eq!(falta, 5, "debe señalar la muestra 5");
            assert_eq!(antes, 4);
            assert_eq!(despues, 6);
        }
        otro => panic!("esperaba Hueco(5), vino {otro:?}"),
    }

    drop(host);

    // ── 5. Y tras reabrir el entorno, sigue detectándolo ─────────
    // (la manipulación está en disco, no en memoria)
    let host2 = MemoryHost::from_lmdb(&dir_s).expect("reabrir");
    let muestras2 = leer_serie(&host2, 10);
    assert_eq!(muestras2.len(), 7, "la baja debe persistir");
    let v2 = cadena::verificar(&muestras2);
    assert!(
        matches!(v2.problema, Some(cadena::ErrorCadena::Hueco { falta: 5, .. })),
        "tras reabrir debe seguir localizando el hueco: {:?}",
        v2.problema
    );
}

#[test]
fn una_muestra_manipulada_en_disco_se_detecta() {
    let dir = std::env::temp_dir().join(format!("lumen-nodo-e2e2-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let dir_s = dir.to_string_lossy().to_string();

    let mut host = MemoryHost::from_lmdb(&dir_s).expect("abrir lmdb");
    let mut prev = String::new();
    for n in 1..=4u64 {
        let m = cadena::encadenar(&prev, &format!("v{n}")).expect("encadenar");
        prev = m.hash.clone();
        host.set("FLOTA", &subs(n), lumen_mlight::Value::String(m.a_texto()))
            .expect("set");
    }

    // Manipular la muestra 2: cambiar el valor SIN recalcular el hash.
    let m2 = cadena::MuestraEncadenada::desde_texto(&{
        host.get("FLOTA", &subs(2)).unwrap().unwrap().as_string()
    })
    .expect("parsear");
    let mut falso = m2.clone();
    falso.valor = "999.9".into();
    host.set("FLOTA", &subs(2), lumen_mlight::Value::String(falso.a_texto()))
        .expect("set falso");

    let muestras = leer_serie(&host, 10);
    let v = cadena::verificar(&muestras);
    assert!(!v.es_integro(), "un valor manipulado DEBE detectarse");
    assert!(
        matches!(v.problema, Some(cadena::ErrorCadena::CadenaRota { .. })),
        "esperaba CadenaRota, vino {:?}",
        v.problema
    );
    drop(host);
}
