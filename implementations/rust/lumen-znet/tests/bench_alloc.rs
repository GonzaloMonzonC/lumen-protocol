//! Mide el coste REAL de la asignación por mensaje en el camino de envío.
//!
//! `flush()` hace `vec![0u8; N]` por cada mensaje. En un envío de N mensajes son
//! N reservas de heap. Este test mide cuánto cuesta eso frente a reutilizar un
//! buffer, que es la posible optimización.

use lumen_znet::DdpMessage;
use lumen_znet::msg_type;
use std::time::Instant;

const ITERS: usize = 50_000;

fn medir<F: FnMut()>(mut f: F) -> f64 {
    for _ in 0..200 { f(); }
    let mut xs = Vec::with_capacity(ITERS);
    for _ in 0..ITERS {
        let t0 = Instant::now();
        f();
        xs.push(t0.elapsed().as_nanos() as f64);
    }
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());
    xs[xs.len() / 2]
}

#[test]
fn asignar_vs_reutilizar() {
    let msg = DdpMessage::new(msg_type::DATA, 1, 7, 0, vec![0x41; 128]);
    let tam = lumen_znet::DDP_HEADER_LEN + msg.body.len();

    // A) reserva nueva por mensaje (lo que hace hoy flush)
    let con_asignacion = medir(|| {
        let buf = vec![0u8; tam];
        std::hint::black_box(&buf);
    });

    // B) buffer reutilizado (pre-reservado fuera del bucle)
    let mut reutilizado = vec![0u8; tam];
    let sin_asignacion = medir(|| {
        reutilizado[0] = 1;
        std::hint::black_box(&reutilizado);
    });

    println!();
    println!("==================================================================");
    println!("COSTE DE LA ASIGNACION POR MENSAJE");
    println!("==================================================================");
    println!("tamaño del frame: {} bytes", tam);
    println!();
    println!("  vec![0u8; N] por mensaje : {:>8.1} ns", con_asignacion);
    println!("  buffer reutilizado       : {:>8.1} ns", sin_asignacion);
    let ahorro = con_asignacion - sin_asignacion;
    println!("  ahorro por mensaje       : {:>8.1} ns", ahorro);
    println!();
    if ahorro > 0.0 {
        println!("  En 1.000 mensajes: {:.0} µs de ahorro", ahorro * 1000.0 / 1000.0);
    }
    println!("==================================================================");
}
