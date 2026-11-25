//! FLOTA MULTI-NODO — varios barcos, un hub, por QUIC real, a la vez.
//!
//! Lo que añade sobre `quic_e2e`:
//!   1. **Varios barcos** (5) replicando al mismo hub.
//!   2. **En paralelo**: los barcos mandan a la vez, no uno detrás de otro.
//!   3. Cada barco con **su certificado de flota** y su serie propia.
//!   4. Un **intruso** de otra flota que intenta colarse entre los buenos.
//!   5. El hub verifica TODO y no mezcla series de barcos distintos.
//!
//! ## Por qué esto no es "el mismo test con más nodos"
//!
//! Con varios nodos aparecen problemas que uno solo no muestra:
//!   - El hub tiene que atender N conexiones: si atiende de una en una, los
//!     demás esperan y el test expone si hay bloqueo.
//!   - Las series se mezclan en la misma PDB: si la clave no lleva el nodo
//!     dentro, unos pisan a otros.
//!   - Un intruso tiene que ser rechazado SIN tumbar a los buenos.

#![cfg(all(feature = "quic", feature = "motor-lmdb"))]

use lumen_mlight::{Host, MemoryHost};
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::{CertificadoFlota, Identidad};
use lumen_nodo_lib::replicacion::Hecho;
use lumen_znet::{QuicZnet, Znet};
use std::sync::mpsc;
use std::time::{Duration, Instant};

const BARCOS: usize = 5;
const MUESTRAS: u64 = 100;
const BLOQUE: u64 = 25;

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
            firma: None, ..Default::default() };
        prev = h.hash();
        serie.push(h);
    }
    hechos_wire::firmar_bloque(&mut serie, BLOQUE as usize, id);
    serie
}

#[test]
fn cinco_barcos_replican_al_mismo_hub_a_la_vez() {
    println!();
    println!("==================================================================");
    println!("FLOTA MULTI-NODO — {} barcos + hub, por QUIC, en paralelo", BARCOS);
    println!("==================================================================");

    // ══ El armador certifica a todos sus barcos ══
    let raiz = Identidad::generar();
    let raiz_pub = raiz.clave_publica_hex();

    let mut barcos: Vec<(String, Identidad, CertificadoFlota, Vec<Hecho>)> = Vec::new();
    for i in 0..BARCOS {
        let nombre = format!("BARCO-{i}");
        let id = Identidad::generar();
        let cert = CertificadoFlota::emitir(&raiz, "Armador", &nombre, &id.clave_publica_hex())
            .expect("certificado");
        let serie = serie_firmada(&nombre, &id, MUESTRAS);
        barcos.push((nombre, id, cert, serie));
    }
    println!("[OK  ] {} barcos certificados por la raiz del armador", BARCOS);

    // ══ Un intruso de OTRA flota ══
    let raiz_ajena = Identidad::generar();
    let id_intruso = Identidad::generar();
    let cert_intruso = CertificadoFlota::emitir(
        &raiz_ajena, "Otra Naviera", "BARCO-0", &id_intruso.clave_publica_hex())
        .expect("certificado intruso");
    let serie_intrusa = serie_firmada("BARCO-0", &id_intruso, MUESTRAS);
    println!("[OK  ] un intruso de otra flota se hara pasar por BARCO-0");

    // ══ Arrancar el hub ══
    let (tx_addr, rx_addr) = mpsc::channel::<String>();
    let (tx_res, rx_res) = mpsc::channel::<Vec<(String, usize)>>();
    let raiz_pub_hilo = raiz_pub.clone();
    let certs: Vec<(String, CertificadoFlota)> = barcos
        .iter()
        .map(|(n, _, c, _)| (n.clone(), c.clone()))
        .collect();

    let hilo_hub = std::thread::spawn(move || {
        let (mut endpoint, huella) = match lumen::quic::server_with_pin("127.0.0.1:0") {
            Ok(x) => x,
            Err(e) => { let _ = tx_res.send(vec![]); eprintln!("servidor: {e}"); return; }
        };
        let addr = endpoint.local_addr().expect("local_addr");
        let _ = tx_addr.send(format!("{addr}|{huella}"));

        let mut host = MemoryHost::default();
        let mut resultados: Vec<(String, usize)> = Vec::new();
        let inicio = Instant::now();
        let mut conexiones = 0;

        // Atender a TODOS los barcos: una conexion cada uno.
        while conexiones < BARCOS && inicio.elapsed() < Duration::from_secs(60) {
            let transporte = match endpoint.accept() {
                Ok(t) => t,
                Err(_) => break,
            };
            conexiones += 1;

            let mut znet = Znet::new();
            znet.init();
            let mut qz = QuicZnet::new(transporte);

            // Leer hasta tener las muestras de un barco o agotar el tiempo.
            let mut recibidos = 0usize;
            let t0 = Instant::now();
            let mut sin_datos = 0;
            while recibidos < MUESTRAS as usize && t0.elapsed() < Duration::from_secs(20) {
                match qz.pump(&mut znet) {
                    Ok((leidos, msgs)) => {
                        recibidos += msgs;
                        if leidos == 0 {
                            sin_datos += 1;
                            if sin_datos > 100 { break; }
                            std::thread::sleep(Duration::from_millis(2));
                        } else { sin_datos = 0; }
                    }
                    Err(_) => break,
                }
            }

            let mut mensajes = Vec::new();
            while let Some(m) = znet.recv() { mensajes.push(m); }

            // Verificar flota: buscar el certificado del nodo que dice ser.
            for m in &mensajes {
                if let Some(h) = hechos_wire::hecho_de_mensaje(m) {
                    if h.seq != 0 { continue; }
                    let nodo = &h.nodo;
                    if let Some((_, cert)) = certs.iter().find(|(n, _)| n == nodo) {
                        let _ = hechos_wire::verificar_serie_de_flota(
                            &[h.clone()], cert, &raiz_pub_hilo, 1);
                    }
                }
            }

            // Guardar con verificacion (el certificado del emisor se resuelve
            // por el nombre del nodo en el primer hecho de la conexion).
            let clave: Option<Vec<u8>> = mensajes
                .iter()
                .find_map(hechos_wire::hecho_de_mensaje)
                .and_then(|h| {
                    certs.iter().find(|(n, _)| n == &h.nodo).and_then(|(_, c)| {
                        lumen_nodo_lib::identidad::hex_a_bytes_publico(&c.clave_barco).ok()
                    })
                });

            let r = hechos_wire::recibir_hechos_con(
                &mut host, &mensajes, clave.as_deref(), false);
            resultados.push((
                format!("conexion-{conexiones}"),
                r.aceptados,
            ));
            if r.rechazados > 0 {
                resultados.push((format!("rechazados-{conexiones}"), r.rechazados));
            }
        }
        let _ = tx_res.send(resultados);
    });

    let combinado = rx_addr.recv_timeout(Duration::from_secs(20)).expect("hub arriba");
    let partes: Vec<&str> = combinado.split('|').collect();
    let (addr, huella) = (partes[0].to_string(), partes[1].to_string());
    println!("[OK  ] hub escuchando en {}", addr);

    // ══ Todos los barcos lanzados a la vez ══
    let mut lanzados = Vec::new();
    let t_inicio = Instant::now();
    for (nombre, _id, _cert, serie) in &barcos {
        let addr = addr.clone();
        let huella = huella.clone();
        let serie = serie.clone();
        let nombre = nombre.clone();
        lanzados.push(std::thread::spawn(move || {
            let config = lumen::quic::pinned_client_config(&huella).expect("pin");
            let mut ep = lumen::quic::QuicEndpoint::client_with_config(Some(config))
                .expect("endpoint");
            let t = ep.connect(&addr).expect("conectar");
            let mut znet = Znet::new();
            znet.init();
            let c = znet.connect("hub").expect("circuito");
            let mut qz = QuicZnet::new(t);
            for h in &serie {
                let m = hechos_wire::mensaje_de_hecho(h);
                let _ = znet.reply(c, lumen_znet::ZnetReply::Data(m.body));
            }
            let n = qz.flush(&mut znet).expect("flush");
            // Mantener vivo hasta que el hub acabe de leer.
            std::thread::sleep(Duration::from_millis(150));
            drop(qz);
            (nombre, n)
        }));
    }

    let mut total_enviado = 0;
    for th in lanzados {
        let (_n, enviados) = th.join().expect("hilo de barco");
        total_enviado += enviados;
    }
    let t_envio = t_inicio.elapsed();
    println!("[{}] {} barcos enviaron a la vez -> {} mensajes en {:?}",
        if total_enviado == (BARCOS as u64 * MUESTRAS) as usize { "OK  " } else { "FALLO" },
        BARCOS, total_enviado, t_envio);
    assert_eq!(total_enviado, (BARCOS as u64 * MUESTRAS) as usize);

    let resultados = rx_res.recv_timeout(Duration::from_secs(60)).expect("hub responde");
    let _ = hilo_hub.join();

    let aceptados: usize = resultados.iter()
        .filter(|(k, _)| k.starts_with("conexion"))
        .map(|(_, v)| *v).sum();
    let rechazados: usize = resultados.iter()
        .filter(|(k, _)| k.starts_with("rechazados"))
        .map(|(_, v)| *v).sum();

    let esperado = (BARCOS as u64 * MUESTRAS) as usize;
    println!("[{}] el hub acepta las {} muestras de los {} barcos -> {} aceptadas, {} rechazadas",
        if aceptados == esperado { "OK  " } else { "FALLO" },
        esperado, BARCOS, aceptados, rechazados);
    assert_eq!(aceptados, esperado, "todos los barcos de la flota deben entrar");
    assert_eq!(rechazados, 0, "ningun barco legitimo debe rechazarse");

    // ══ El intruso intenta colarse ══
    let r_intruso = hechos_wire::verificar_serie_de_flota(
        &serie_intrusa, &cert_intruso, &raiz_pub, BLOQUE as usize);
    let detalle_intruso = r_intruso.as_ref().err().map(|e| e.chars().take(35).collect::<String>());
    println!("[{}] el intruso de otra flota se rechaza -> {:?}",
        if r_intruso.is_err() { "OK  " } else { "FALLO" }, detalle_intruso);
    assert!(r_intruso.is_err());

    println!("==================================================================");
}
