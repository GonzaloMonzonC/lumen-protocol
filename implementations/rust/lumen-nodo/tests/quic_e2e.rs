//! E2E POR QUIC REAL — el barco y el hub hablan por un socket de verdad.
//!
//! ## Qué cambia respecto a los tests anteriores
//!
//! Los tests previos construían los mensajes DDP y los pasaban **en memoria**.
//! Eso demuestra que el protocolo es correcto, pero no que funcione sobre un
//! cable. Aquí:
//!
//! - Hay un **servidor QUIC** escuchando en 127.0.0.1 (puerto del sistema).
//! - Hay un **cliente QUIC** que se conecta de verdad.
//! - Los frames viajan por TLS 1.3 con certificado autofirmado y pin.
//! - Cada extremo tiene su `QuicZnet` y su LMDB.
//!
//! Lo que sigue igual: la verificación. Los hechos se comprueban al llegar,
//! con cadena, sello y flota. El transporte no se fía.
//!
//! ## Por qué va en un hilo
//!
//! `QuicEndpoint::accept()` bloquea hasta que llega una conexión. El cliente
//! tiene que existir en otro hilo o el test se queda esperando para siempre.

#![cfg(all(feature = "quic", feature = "motor-lmdb"))]

use lumen_mlight::{Host, MemoryHost};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::{CertificadoFlota, Identidad};
use lumen_nodo_lib::replicacion::Hecho;
use lumen_znet::{QuicZnet, Znet};
use std::sync::mpsc;

const MUESTRAS: u64 = 200;
const BLOQUE: u64 = 50;

fn serie_firmada(nodo: &str, id: &Identidad, n: u64) -> Vec<Hecho> {
    let mut serie = Vec::with_capacity(n as usize);
    let mut prev = String::new();
    for i in 0..n {
        let h = Hecho {
            nodo: nodo.into(),
            serie: "gps".into(),
            seq: i,
            clave: "gps".into(),
            valor: format!("lat={:.6}", 41.0 + (i as f64) * 1e-6),
            prev_hash: prev.clone(),
            ts: i,
            firma: None,
        };
        prev = h.hash();
        serie.push(h);
    }
    hechos_wire::firmar_bloque(&mut serie, BLOQUE as usize, id);
    serie
}

#[test]
fn el_barco_manda_su_bitacora_por_quic_y_el_hub_la_verifica() {
    println!();
    println!("==================================================================");
    println!("E2E POR QUIC REAL — {} muestras por un socket TLS 1.3", MUESTRAS);
    println!("==================================================================");

    // ══ El armador y los barcos ══
    let raiz = Identidad::generar();
    let raiz_pub = raiz.clave_publica_hex();
    let barco = Identidad::generar();
    let cert_barco =
        CertificadoFlota::emitir(&raiz, "Armador", "BARCO-A", &barco.clave_publica_hex())
            .expect("certificado del barco");

    // ══ El barco prepara su bitacora con los sellos firmados ══
    let serie_local = serie_firmada("BARCO-A", &barco, MUESTRAS);

    // ══ 1. Arrancar el servidor QUIC en un hilo ══
    let (tx_listo, rx_listo) = mpsc::channel::<String>();
    let (tx_res, rx_res) = mpsc::channel::<Result<(usize, usize), String>>();

    let raiz_pub_hilo = raiz_pub.clone();
    let cert_hilo = cert_barco.clone();
    let clave_barco_hilo = barco.clave_publica();

    let hilo_servidor = std::thread::spawn(move || {
        // Servidor con certificado autofirmado; devuelve su huella para el pin.
        let (mut endpoint, huella) = match lumen::quic::server_with_pin("127.0.0.1:0") {
            Ok(x) => x,
            Err(e) => {
                let _ = tx_res.send(Err(format!("servidor: {e}")));
                return;
            }
        };
        let addr = match endpoint.local_addr() {
            Ok(a) => a,
            Err(e) => {
                let _ = tx_res.send(Err(format!("local_addr: {e}")));
                return;
            }
        };
        let _ = tx_listo.send(format!("{addr}|{huella}"));

        // Aceptar UNA conexion.
        let transporte = match endpoint.accept() {
            Ok(t) => t,
            Err(e) => {
                let _ = tx_res.send(Err(format!("accept: {e}")));
                return;
            }
        };

        // El hub tiene su propio LMDB (aqui en memoria: el disco ya se probo).
        let mut host = MemoryHost::default();
        let mut znet = Znet::new();
        znet.init();
        let mut qz = QuicZnet::new(transporte);

        // Recibir hasta tener los mensajes esperados.
        //
        // OJO: `poll`/`pump` devuelven 0 BOTH cuando "no hay nada nuevo" como en
        // EOF. Usar el 0 para decidir el final corta la conexion a la primera
        // lectura sin datos y el cliente se queda con "connection lost".
        // Aqui se cuenta lo recibido y se corta cuando ya esta todo.
        let esperados = MUESTRAS as usize;
        let mut recibidos = 0usize;
        let mut intentos_sin_datos = 0;
        loop {
            match qz.pump(&mut znet) {
                Ok((leidos, msgs)) => {
                    recibidos += msgs;
                    if recibidos >= esperados {
                        break;
                    }
                    if leidos == 0 {
                        intentos_sin_datos += 1;
                        // Si no llega nada en muchos ciclos seguidos, el par cerro.
                        if intentos_sin_datos > 200 {
                            break;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(2));
                    } else {
                        intentos_sin_datos = 0;
                    }
                }
                Err(_) => break,
            }
        }

        // Sacar los mensajes que quedaron en cola y verificarlos.
        //
        // OJO: `pump`/`poll` meten los mensajes con `push_incoming`, que es la
        // cola de ENTRADA y se lee con `recv()`. `recv_circuit()` lee la cola de
        // SALIDA (lo que se responde). Usar la equivocada da 0 mensajes aunque
        // hayan llegado: el contador de `pump` dice 200 y la lista sale vacia.
        let mut mensajes = Vec::new();
        while let Some(m) = znet.recv() {
            mensajes.push(m);
        }

        let r = hechos_wire::recibir_hechos_con(
            &mut host, &mensajes, Some(&clave_barco_hilo), false);
        let guardados = hechos_store::contar_serie(&host, "BARCO-A", "gps");
        let _ = &r;

        // La verificacion de flota, sobre lo guardado.
        let serie = hechos_store::leer_serie(&host, "BARCO-A", "gps");
        let flota = hechos_wire::verificar_serie_de_flota(
            &serie, &cert_hilo, &raiz_pub_hilo, BLOQUE as usize);

        match flota {
            Ok(n) => {
                let _ = tx_res.send(Ok((guardados as usize, n)));
            }
            Err(e) => {
                let _ = tx_res.send(Err(format!(
                    "flota: {e} (guardados {guardados})")));
            }
        }
    });

    // ══ 2. El cliente espera la dirección y se conecta de verdad ══
    let (addr, huella) = match rx_listo.recv_timeout(std::time::Duration::from_secs(20)) {
        Ok(x) => {
            let partes: Vec<&str> = x.split('|').collect();
            (partes[0].to_string(), partes[1].to_string())
        }
        Err(e) => panic!("el servidor no arranco: {e}"),
    };
    println!("[OK  ] servidor QUIC escuchando en {} (huella {}...)", addr, &huella[..16]);

    let config = lumen::quic::pinned_client_config(&huella).expect("cliente con pin");
    let mut cliente_endpoint =
        lumen::quic::QuicEndpoint::client_with_config(Some(config)).expect("endpoint cliente");
    let transporte = cliente_endpoint.connect(&addr).expect("conectar por QUIC");
    println!("[OK  ] cliente conectado por TLS 1.3");

    let mut znet = Znet::new();
    znet.init();
    let circuito = znet.connect("hub").expect("circuito");
    let mut qz = QuicZnet::new(transporte);

    // El barco encola un mensaje por hecho y hace flush por el cable.
    // Cada `reply` mete el mensaje en la cola de salida del circuito; `flush`
    // los convierte en frames LUMEN y los escribe. NO hace falta pasar por
    // push_incoming: eso es la cola de ENTRADA y duplicaria los mensajes.
    for h in &serie_local {
        let m = hechos_wire::mensaje_de_hecho(h);
        let _ = znet.reply(circuito, lumen_znet::ZnetReply::Data(m.body));
    }
    let enviados = qz.flush(&mut znet).expect("flush por QUIC");
    println!("[OK  ] el barco envia {} mensajes por el cable", enviados);
    assert_eq!(enviados, MUESTRAS as usize, "debe enviar uno por hecho");

    // ══ 3. El hub responde con el resultado ══
    // Se espera AQUI, con la conexion aun viva, y se suelta despues.
    let resultado = rx_res.recv_timeout(std::time::Duration::from_secs(30));
    drop(qz);
    drop(cliente_endpoint);
    let _ = hilo_servidor.join();

    match resultado {
        Ok(Ok((guardados, sellos))) => {
            println!("[{}] el hub guarda y verifica por QUIC -> {} muestras, {} sellos",
                if guardados == MUESTRAS as usize { "OK  " } else { "FALLO" }, guardados, sellos);
            assert_eq!(guardados, MUESTRAS as usize, "deben llegar todas por el cable");
            assert_eq!(sellos, (MUESTRAS / BLOQUE) as usize);
        }
        Ok(Err(e)) => panic!("el hub fallo: {e}"),
        Err(e) => panic!("el hub no respondio: {e}"),
    }

    println!("==================================================================");
}
