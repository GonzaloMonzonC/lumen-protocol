//! Prueba end-to-end del pin entre dos nodos REALES.
//!
//! No prueba una función: prueba el camino completo que usa el nodo.
//!   1. Un nodo servidor arranca y escucha; expone la huella de su certificado.
//!   2. Un cliente con ESA huella conecta, manda un frame DDP y recibe ACK.
//!   3. Un cliente con OTRA huella NO conecta (el handshake se cae).
//!
//! Requiere la feature `quic`.

#![cfg(feature = "quic")]

use std::thread;
use std::time::Duration;

use lumen::frame::{self, ParseResult};
use lumen::quic::{pinned_client_config, server_with_pin, QuicEndpoint};
use lumen::transport::Transport;

#[test]
fn un_nodo_con_pin_solo_acepta_a_quien_tiene_su_huella() {
    // ── 1. Nodo servidor: arranca y nos da su huella ──────────────
    let (mut servidor, huella) = server_with_pin("127.0.0.1:0").expect("servidor");
    let addr = servidor.local_addr().expect("addr").to_string();
    assert_eq!(huella.len(), 64, "la huella debe ser sha256 hex");
    assert!(
        huella.chars().all(|c| c.is_ascii_hexdigit()),
        "huella debe ser hex: {huella}"
    );

    // ── 2. Cliente con la huella BUENA: debe completar el viaje ───
    let hilo_ok = thread::spawn(move || -> Result<Vec<u8>, String> {
        let mut t = servidor.accept().map_err(|e| format!("accept: {e}"))?;

        // Leer un frame completo.
        let mut buf = Vec::new();
        let cuerpo = loop {
            let mut chunk = [0u8; 4096];
            match t.read(&mut chunk) {
                Ok(0) => return Err("stream cerrado".into()),
                Ok(n) => buf.extend_from_slice(&chunk[..n]),
                Err(e) => return Err(format!("read: {e}")),
            }
            if let ParseResult::Complete { frame, consumed } = frame::parse(&buf) {
                let payload = frame.payload.to_vec();
                buf.drain(..consumed);
                break payload;
            }
        };

        // Responder con el mismo payload (eco firmado por el transporte TLS).
        let mut out = vec![0u8; frame::build_size(cuerpo.len())];
        let n = frame::build(0x02, 0, &cuerpo, &mut out);
        t.write_all(&out[..n]).map_err(|e| format!("write: {e}"))?;
        t.flush().map_err(|e| format!("flush: {e}"))?;
        thread::sleep(Duration::from_millis(300));
        Ok(cuerpo)
    });

    thread::sleep(Duration::from_millis(300));

    let cfg_buena = pinned_client_config(&huella).expect("config con pin bueno");
    let mut ep = QuicEndpoint::client_with_config(Some(cfg_buena)).expect("cliente");
    let mut transporte = ep
        .connect(&addr)
        .expect("con el pin correcto DEBE conectar");

    let carga = b"^SYS(\"JOURNAL\",1)=barco-A^lat41.38";
    let mut out = vec![0u8; frame::build_size(carga.len())];
    let n = frame::build(0x01, 0, carga, &mut out);
    transporte
        .write_all(&out[..n])
        .and_then(|_| transporte.flush())
        .expect("debe poder escribir");

    // Leer el eco.
    let mut buf = Vec::new();
    let eco = loop {
        let mut chunk = [0u8; 4096];
        let n = transporte.read(&mut chunk).expect("read del eco");
        assert!(n > 0, "stream cerrado esperando eco");
        buf.extend_from_slice(&chunk[..n]);
        if let ParseResult::Complete { frame, consumed } = frame::parse(&buf) {
            let p = frame.payload.to_vec();
            buf.drain(..consumed);
            break p;
        }
    };
    assert_eq!(eco, carga, "el frame debe volver intacto");

    let visto = hilo_ok.join().unwrap().expect("el servidor debe ver el frame");
    assert_eq!(visto, carga, "el servidor debe recibir la carga exacta");
    drop(transporte);

    // ── 3. Cliente con huella MALA: NO debe conectar ──────────────
    let (mut servidor2, _h2) = server_with_pin("127.0.0.1:0").expect("servidor 2");
    let addr2 = servidor2.local_addr().expect("addr2").to_string();
    let hilo_malo = thread::spawn(move || {
        // Si el pin funciona esto no acepta nunca nada; no assertamos aquí.
        let _ = servidor2.accept();
    });

    thread::sleep(Duration::from_millis(300));
    let huella_mala = "0".repeat(64);
    let cfg_mala = pinned_client_config(&huella_mala).expect("config con pin malo");
    let mut ep2 = QuicEndpoint::client_with_config(Some(cfg_mala)).expect("cliente 2");
    let intento = ep2.connect(&addr2);
    assert!(
        intento.is_err(),
        "un nodo con pin NO debe aceptar a un cliente que no tiene su huella"
    );
    drop(ep2);
    let _ = hilo_malo.join();
}

#[test]
fn dos_huellas_distintas_no_son_intercambiables() {
    let (_s1, h1) = server_with_pin("127.0.0.1:0").expect("s1");
    let (_s2, h2) = server_with_pin("127.0.0.1:0").expect("s2");
    assert_ne!(h1, h2, "cada nodo debe tener su propia huella");
    // Y las dos son huellas válidas.
    assert!(pinned_client_config(&h1).is_ok());
    assert!(pinned_client_config(&h2).is_ok());
}
