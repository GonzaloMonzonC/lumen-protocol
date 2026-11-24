//! Test de regresión: QuicTransport NO debe entregar bytes de relleno.
//!
//! Bug real encontrado el 24-nov-2026 al conectar dos nodos `lumen-nodo`:
//! `read_buffer` se redimensiona a 65536 con ceros y `recv.read` solo llena
//! los primeros `n` bytes. La comprobación de "quedan pendientes" es
//! `read_pos < read_buffer.len()`, que compara contra el tamaño del BUFFER
//! (65536) y no contra los bytes realmente leídos → tras la primera lectura
//! real, la siguiente llamada entrega ~65 KB de ceros.
//!
//! Síntoma observable: el receptor ve frames válidos de longitud 0 y basura.
//! Este test debe fallar ANTES del arreglo y pasar después.

#![cfg(feature = "quic")]

use std::io::{Read, Write};
use std::thread;
use std::time::Duration;

use lumen::quic::QuicEndpoint;
use lumen::transport::Transport;

#[test]
fn leer_un_frame_pequeno_no_devuelve_relleno() {
    let mut servidor = QuicEndpoint::server("127.0.0.1:0").expect("servidor");
    let addr = servidor.local_addr().expect("addr").to_string();

    const CARGA: &[u8] = b"^SYS(\"JOURNAL\",1)=p1^p2";
    let carga_vec = CARGA.to_vec();

    let hilo = thread::spawn(move || -> Vec<u8> {
        let mut t = servidor.accept().expect("accept");
        // Leer hasta tener la carga completa. Si el transporte mete relleno,
        // lo veremos aquí.
        let mut visto = Vec::new();
        let inicio = std::time::Instant::now();
        while visto.len() < carga_vec.len() {
            if inicio.elapsed() > Duration::from_secs(5) {
                return visto; // salimos con lo que haya, para que el assert lo enseñe
            }
            let mut chunk = [0u8; 256];
            match t.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) => {
                    visto.extend_from_slice(&chunk[..n]);
                    if n > 0 && visto.len() > carga_vec.len() {
                        // Nos han dado MÁS bytes de los enviados: relleno.
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        // Mantener vivo un momento para que el emisor no corte.
        thread::sleep(Duration::from_millis(200));
        visto
    });

    thread::sleep(Duration::from_millis(300));
    let mut cliente = QuicEndpoint::client().expect("cliente");
    let mut t = cliente.connect(&addr).expect("connect");
    t.write_all(CARGA).expect("write");
    t.flush().expect("flush");

    let visto = hilo.join().expect("hilo");

    assert_eq!(
        visto.len(),
        CARGA.len(),
        "el receptor debe ver EXACTAMENTE los {} bytes enviados, vio {} \
         (si es mucho mayor, el transporte esta entregando relleno del buffer)",
        CARGA.len(),
        visto.len()
    );
    assert_eq!(&visto[..], CARGA, "los bytes deben llegar intactos");
}

#[test]
fn dos_lecturas_seguidas_no_reptien_ni_inventan_bytes() {
    let mut servidor = QuicEndpoint::server("127.0.0.1:0").expect("servidor");
    let addr = servidor.local_addr().expect("addr").to_string();

    let hilo = thread::spawn(move || -> (Vec<u8>, Vec<u8>) {
        let mut t = servidor.accept().expect("accept");
        let mut primero = vec![0u8; 4];
        let n1 = t.read(&mut primero).unwrap_or(0);
        primero.truncate(n1);
        let mut segundo = vec![0u8; 64];
        let n2 = t.read(&mut segundo).unwrap_or(0);
        segundo.truncate(n2);
        thread::sleep(Duration::from_millis(200));
        (primero, segundo)
    });

    thread::sleep(Duration::from_millis(300));
    let mut cliente = QuicEndpoint::client().expect("cliente");
    let mut t = cliente.connect(&addr).expect("connect");
    t.write_all(b"ABCD").expect("write 1");
    t.flush().expect("flush");
    thread::sleep(Duration::from_millis(100));
    t.write_all(b"EFGH").expect("write 2");
    t.flush().expect("flush");

    let (p, s) = hilo.join().expect("hilo");
    let todos = [p.clone(), s.clone()].concat();
    assert_eq!(
        todos,
        b"ABCDEFGH".to_vec(),
        "las dos lecturas juntas deben dar exactamente lo enviado (primera={p:?} segunda={s:?})"
    );
    assert!(
        s.len() <= 4,
        "la segunda lectura no debe traer mas de lo que falta, trajo {} bytes",
        s.len()
    );
}
