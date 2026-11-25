//! Mide el envío por LOTES (el caso real: un nodo que manda N mensajes).
//!
//! Compara el coste de mandar 1.000 mensajes por flush(), que es donde la
//! reserva por mensaje dolía. Con el buffer reutilizado debe bajar.

use lumen::transport::Transport;
use lumen_znet::{msg_type, DdpMessage, QuicZnet, Znet};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Instant;

/// Sumidero en memoria: cuenta bytes y no guarda nada, para medir solo el coste
/// del codec y no de la recolección de basura del Vec de salida.
struct Sumidero {
    total: Arc<AtomicUsize>,
}

impl Transport for Sumidero {
    fn read(&mut self, _buf: &mut [u8]) -> std::io::Result<usize> {
        Ok(0)
    }
    fn write_all(&mut self, buf: &[u8]) -> std::io::Result<()> {
        self.total.fetch_add(buf.len(), Ordering::Relaxed);
        Ok(())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

#[test]
fn envio_por_lotes() {
    const N: usize = 1000;
    const REPETICIONES: usize = 200;

    let mut tiempos = Vec::with_capacity(REPETICIONES);
    let mut bytes_total = 0;

    for _ in 0..REPETICIONES {
        let contador = Arc::new(AtomicUsize::new(0));
        let sumidero = Sumidero { total: contador.clone() };
        let mut backend = QuicZnet::new(sumidero);
        let mut znet = Znet::new();
        znet.init();
        let c = znet.connect("hub").unwrap();

        // Encolar N respuestas CON CARGA (el caso real: un agente devolviendo datos).
        for _ in 0..N {
            znet.reply(c, lumen_znet::ZnetReply::Data(vec![0x41u8; 128]))
                .unwrap();
        }

        let t0 = Instant::now();
        backend.flush(&mut znet).unwrap();
        tiempos.push(t0.elapsed().as_nanos() as f64);
        bytes_total = contador.load(Ordering::Relaxed);
    }

    tiempos.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let p50 = tiempos[tiempos.len() / 2];
    let p99 = tiempos[(tiempos.len() as f64 * 0.99) as usize];

    println!();
    println!("==================================================================");
    println!("ENVIO POR LOTES — {} mensajes por flush", N);
    println!("==================================================================");
    println!("bytes escritos por lote : {}", bytes_total);
    println!("p50 por lote            : {:.1} µs", p50 / 1000.0);
    println!("p99 por lote            : {:.1} µs", p99 / 1000.0);
    println!("por mensaje (p50)       : {:.1} ns", p50 / N as f64);
    println!("mensajes/s (p50)        : {:.0}", 1_000_000_000.0 / (p50 / N as f64));
    println!("==================================================================");
}
