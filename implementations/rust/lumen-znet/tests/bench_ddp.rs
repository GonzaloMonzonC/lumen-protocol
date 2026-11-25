//! Benchmark del codec DDP — medir ANTES de optimizar.
//!
//! Preguntas que responde:
//!   1. ¿Cuánto cuesta encode/decode de un mensaje típico?
//!   2. ¿Dónde se va el tiempo: en la cabecera o en copiar la carga?
//!   3. ¿Merece la pena una reserva distinta de capacidad?
//!
//! Uso: cargo test --release --test bench_ddp -- --nocapture

use lumen_znet::{msg_type, DdpMessage, DDP_HEADER_LEN};
use std::time::Instant;

const WARMUP: usize = 500;
const ITERS: usize = 200_000;

fn pct(xs: &[f64], p: f64) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    let i = ((xs.len() - 1) as f64 * p).round() as usize;
    xs[i.min(xs.len() - 1)]
}

/// Devuelve (p50, p99) en nanosegundos, midiendo en dos mitades.
fn medir<F: FnMut()>(mut f: F) -> (f64, f64) {
    for _ in 0..WARMUP {
        f();
    }
    let mitad = ITERS / 2;
    let tanda = |n: usize, f: &mut F| -> Vec<f64> {
        let mut xs = Vec::with_capacity(n);
        for _ in 0..n {
            let t0 = Instant::now();
            f();
            xs.push(t0.elapsed().as_nanos() as f64);
        }
        xs
    };
    let mut a = tanda(mitad, &mut f);
    let mut b = tanda(mitad, &mut f);
    // Si la 2a mitad se degrada (calor), usar solo la 1a.
    a.sort_by(|x, y| x.partial_cmp(y).unwrap());
    b.sort_by(|x, y| x.partial_cmp(y).unwrap());
    let m1 = pct(&a, 0.5);
    let m2 = pct(&b, 0.5);
    let xs = if m2 > m1 * 1.2 { a } else { let mut v = a; v.extend(b); v.sort_by(|x,y| x.partial_cmp(y).unwrap()); v };
    (pct(&xs, 0.5), pct(&xs, 0.99))
}

#[test]
fn bench_codec_ddp() {
    let cargas: Vec<(&str, usize)> = vec![
        ("vacio", 0),
        ("comando (8 B)", 8),
        ("mensaje (128 B)", 128),
        ("payload (1 KB)", 1024),
        ("payload (16 KB)", 16384),
    ];

    println!();
    println!("==================================================================");
    println!("CODEC DDP — medición base (antes de optimizar)");
    println!("==================================================================");
    println!("iters={} por caso, warmup={}", ITERS, WARMUP);
    println!("Cabecera actual: {} bytes (tipo 1 + num1 2 + num2 2 + flag 1)", DDP_HEADER_LEN);
    println!();
    println!("{:<18} {:>10} {:>10} {:>10} {:>10} {:>12}", "caso", "enc p50", "enc p99", "dec p50", "dec p99", "ns/byte dec");
    println!("{}", "-".repeat(76));

    for (nombre, tam) in cargas {
        let cuerpo = vec![0x41u8; tam];
        let msg = DdpMessage::new(msg_type::DATA, 0x1234, 7, 0, cuerpo);

        let (e50, e99) = medir(|| {
            let m = &msg;
            std::hint::black_box(m.encode());
        });

        let bytes = msg.encode();
        let (d50, d99) = medir(|| {
            std::hint::black_box(DdpMessage::decode(&bytes).unwrap());
        });

        let por_byte = if tam > 0 { d50 / (tam as f64) } else { 0.0 };
        println!(
            "{:<18} {:>9.1}n {:>9.1}n {:>9.1}n {:>9.1}n {:>11.3}",
            nombre, e50, e99, d50, d99, por_byte
        );
    }

    println!();
    println!("Lectura: si 'enc' y 'dec' crecen proporcionalmente con el tamaño, el");
    println!("tiempo es COPIA de la carga (memcpy), no la cabecera. En ese caso");
    println!("optimizar la cabecera no sirve de nada: hay que evitar la copia.");
    println!("==================================================================");
}
