//! Banco de verificacion para ARM — mide por FASES, con reloj externo.
//!
//! ## Por que por fases y con reloj externo
//!
//! El kernel 3.2 de la NAS hace panic en `SystemTime::now()` y en
//! `Instant::now()` (Os code 22, InvalidInput). No se puede medir desde dentro.
//!
//! Solucion: el binario hace UNA fase por ejecucion y el shell mide cada una
//! con `date +%s%N`. Asi el tiempo total incluye el arranque del proceso
//! (~5-10 ms), que se mide aparte con la fase `nada` para restarlo.
//!
//! Fases:
//!   nada    solo arranca y sale (tara del arranque)
//!   cadena  N hashes encadenados sha256
//!   firmar  N firmas Ed25519
//!   ver     N verificaciones Ed25519
//!   sellos  firmar + verificar N/bloque sellos
//!
//! Uso: bench-cadenas <fase> <n> [bloque]

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier};
use sha2::{Digest, Sha256};
use std::hint::black_box;

fn hash_muestra(prev: &str, valor: &str) -> String {
    let mut h = Sha256::new();
    h.update(prev.as_bytes());
    h.update(valor.as_bytes());
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

fn sello_bloque(sello_previo: &str, hashes: &[String]) -> String {
    let mut h = Sha256::new();
    h.update(sello_previo.as_bytes());
    for x in hashes {
        h.update(x.as_bytes());
    }
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let fase = a.get(1).cloned().unwrap_or_else(|| "nada".to_string());
    let n: usize = a.get(2).and_then(|v| v.parse().ok()).unwrap_or(1000);
    let bloque: usize = a.get(3).and_then(|v| v.parse().ok()).unwrap_or(100);

    let mut csprng = rand::rngs::OsRng;
    let sk = SigningKey::generate(&mut csprng);
    let vk = sk.verifying_key();

    // La fase 'nada' debe NO hacer nada: antes construia la serie de hashes y
    // la tara salia de 846 ms, ocultando que la cadena de 21.600 tarda 33 ms.
    if fase == "nada" {
        println!("nada n={n}");
        return;
    }

    // Serie de hashes: base comun para las fases que la necesitan.
    // La fase 'cadena' mide SOLO la construccion, asi que se hace aqui.
    let mut hashes: Vec<String> = Vec::with_capacity(n);
    let mut prev = String::new();
    for i in 0..n {
        let h = hash_muestra(&prev, &format!("lat=41.{i}"));
        prev = h.clone();
        hashes.push(h);
    }

    match fase.as_str() {
        "nada" => {
            // Tara del arranque.
        }
        "cadena" => {
            // La construccion ya ocurrio arriba (fuera del match no hay otra).
            // Aqui solo se impide que el optimizador la elimine.
            black_box(&hashes);
        }
        "firmar" => {
            let mut acc = 0u64;
            for i in 0..n {
                let msg = format!("v2|BARCO|gps|{i}|inst-A|0|gps|lat=41.{i}");
                let m = msg.as_bytes();
                let s: Signature = sk.sign(m);
                acc = acc.wrapping_add(s.to_bytes()[0] as u64);
            }
            black_box(acc);
        }
        "ver" => {
            // Se firman primero (fuera de la medicion mental: el shell mide
            // TODO, pero esta fase es la dominante para verificar).
            let mut firmas: Vec<(Vec<u8>, Signature)> = Vec::with_capacity(n);
            for i in 0..n {
                let msg = format!("v2|BARCO|gps|{i}|inst-A|0|gps|lat=41.{i}");
                let m = msg.into_bytes();
                let s = sk.sign(&m);
                firmas.push((m, s));
            }
            let mut ok = 0u64;
            for (m, s) in &firmas {
                if vk.verify(m, s).is_ok() {
                    ok += 1;
                }
            }
            black_box(ok);
        }
        "sellos" => {
            let mut sellos: Vec<(Vec<u8>, Signature)> = Vec::new();
            let mut prev_sello = String::new();
            let mut inicio = 0usize;
            while inicio + bloque <= n {
                let s = sello_bloque(&prev_sello, &hashes[inicio..inicio + bloque]);
                let msg = format!("LUMEN-SELLO|FLOTA|gps|{}|{s}", inicio / bloque);
                let m: Vec<u8> = msg.into_bytes();
                let sig = sk.sign(&m);
                sellos.push((m, sig));
                prev_sello = s;
                inicio += bloque;
            }
            let mut ok = 0u64;
            for (m, s) in &sellos {
                if vk.verify(m, s).is_ok() {
                    ok += 1;
                }
            }
            black_box(ok);
        }
        otra => {
            eprintln!("fase desconocida: {otra}");
            std::process::exit(2);
        }
    }
    println!("{fase} n={n}");
}
