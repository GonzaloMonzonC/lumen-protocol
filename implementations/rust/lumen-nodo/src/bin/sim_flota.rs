//! `sim-flota` — nodos reales escribiendo Y replicando a un hub por QUIC.
//!
//! ## Qué es
//!
//! El escenario del paper: una flota que converge. Cada nodo escribe su
//! telemetría en su LMDB **y la manda a un hub** que la verifica, comprueba la
//! pertenencia a la flota y la guarda.
//!
//! ## Modos
//!
//! ```text
//! sim-flota hub <puerto> <dir> <raiz-pub>
//!     Escucha, acepta flotas, verifica y guarda. Imprime el resumen.
//!
//! sim-flota barco <addr-hub> <dir> <n-muestras> <nome-del-barco> <raiz-priv>
//!     Escribe N muestras firmadas y las replica al hub.
//! ```
//!
//! Sin firma de flota todavía no se puede: la raíz del armador certifica al
//! barco, y el hub comprueba la pertenencia. Aquí se usa la identidad directa
//! para medir el circuito completo.

use lumen_mlight::Host;
use lumen_nodo_lib::escritura::Escritor;
use lumen_nodo_lib::hechos_store;
use lumen_nodo_lib::hechos_wire;
use lumen_nodo_lib::identidad::Identidad;
use lumen_nodo_lib::replicacion::{Hecho, PerfilReplicacion};
use lumen_znet::{QuicZnet, Znet};

fn ahora() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_micros())
        .unwrap_or(0)
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    if a.len() < 2 {
        eprintln!("uso: {} hub|barco ...", a[0]);
        std::process::exit(2);
    }
    match a[1].as_str() {
        "hub" => hub(&a),
        "barco" => barco(&a),
        otro => {
            eprintln!("modo desconocido: {otro}");
            std::process::exit(2);
        }
    }
}

/// El hub: acepta barcos, verifica y guarda.
/// El hub: acepta barcos, verifica y guarda.
///
/// ## Por que un hilo por conexion
///
/// accept() bloquea y pump() espera datos. Si se atiende una conexion de
/// principio a fin antes de volver a accept(), los demas barcos se encuentran
/// el puerto sin atender y salta ConnectionRefused. Con 20 barcos a la vez eso
/// pasa siempre.
fn hub(a: &[String]) {
    if a.len() < 5 {
        eprintln!("uso: {} hub <puerto> <dir> <n-barcos-esperados>", a[0]);
        std::process::exit(2);
    }
    let puerto: u16 = a[2].parse().expect("puerto");
    let dir = a[3].clone();
    let esperados: usize = a[4].parse().expect("n-barcos");

    let (mut ep, huella) = lumen::quic::server_with_pin(&format!("127.0.0.1:{puerto}"))
        .expect("servidor quic");
    println!("LISTO {} {}", ep.local_addr().expect("addr"), huella);

    let mut host = lumen_mlight::MemoryHost::from_lmdb_con_durabilidad(&dir, true)
        .expect("lmdb hub");

    let t0 = ahora();
    let mut total_aceptados = 0usize;
    let mut total_rechazados = 0usize;
    let mut total_conflictos = 0usize;
    let mut barcos = 0usize;

    while barcos < esperados {
        let t = match ep.accept() {
            Ok(t) => t,
            Err(e) => {
                eprintln!("accept: {e:?}");
                break;
            }
        };
        barcos += 1;

        // Cada conexion en su hilo: leer y devolver los mensajes.
        let hilo = std::thread::spawn(move || {
            let mut znet = Znet::new();
            znet.init();
            let mut qz = QuicZnet::new(t);
            let mut mensajes: Vec<lumen_znet::DdpMessage> = Vec::new();
            let mut sin_datos = 0;
            loop {
                match qz.pump(&mut znet) {
                    // pump devuelve (ENVIADOS, RECIBIDOS). El primero NO es
                    // 'leidos': confundirlos corta la conexion siempre.
                    Ok((_e, recibidos)) => {
                        if recibidos == 0 {
                            sin_datos += 1;
                            if sin_datos > 1500 {
                                break; // 3 s de silencio
                            }
                            std::thread::sleep(std::time::Duration::from_millis(2));
                            continue;
                        }
                        sin_datos = 0;
                    }
                    Err(_) => break,
                }
                let mut fin = false;
                while let Some(m) = znet.recv() {
                    if m.body.as_slice() == b"FIN" {
                        fin = true;
                        break;
                    }
                    mensajes.push(m);
                }
                if fin {
                    break;
                }
            }
            mensajes
        });

        let mensajes = hilo.join().unwrap_or_default();
        let r = hechos_wire::recibir_hechos(&mut host, &mensajes, None);
        total_aceptados += r.aceptados;
        total_rechazados += r.rechazados;
        total_conflictos += r.conflictos;
        println!(
            "BARCO {} recibidos={} aceptados={} rechazados={} conflictos={}",
            barcos, mensajes.len(), r.aceptados, r.rechazados, r.conflictos
        );
    }

    let ms = ahora().saturating_sub(t0);
    let series = hechos_store::contar_serie(&host, "BARCO-A", "gps");
    println!(
        "FIN barcos={} aceptados={} rechazados={} conflictos={} serie_principal={} ms={}",
        barcos, total_aceptados, total_rechazados, total_conflictos, series, ms
    );
}


/// Un barco: escribe N muestras y las replica al hub.
fn barco(a: &[String]) {
    if a.len() < 7 {
        eprintln!("uso: {} barco <addr-hub:puerto> <huella> <dir> <n> <nombre> <clave-priv-hex>",
            a[0]);
        std::process::exit(2);
    }
    let addr = &a[2];
    let huella = &a[3];
    let dir = &a[4];
    let n: u64 = a[5].parse().expect("n");
    let nombre = &a[6];
    let clave_priv = if a.len() > 7 { Some(a[7].clone()) } else { None };

    let id = match clave_priv {
        Some(h) => Identidad::desde_hex(&h).expect("clave"),
        None => Identidad::generar(),
    };
    let perfil = PerfilReplicacion::barco();

    // 1. Escribir la bitacora en local, con el Escritor (respeta el perfil).
    let mut host = lumen_mlight::MemoryHost::from_lmdb_con_durabilidad(dir, true)
        .expect("lmdb barco");
    let inst = format!("inst-{nombre}");
    let t_esc0 = ahora();
    let mut serie: Vec<Hecho> = Vec::with_capacity(n as usize);
    {
        let mut prev = String::new();
        let mut w = Escritor::nuevo(&mut host, &perfil).expect("escritor");
        for i in 0..n {
            let mut h = Hecho::v2(
                nombre, "gps", i, &inst, 0, "gps",
                &format!("lat=41.{i}"), &prev, i,
            );
            h.firmar(&id);
            prev = h.hash();
            w.escribir(&h).expect("escribir");
            serie.push(h);
        }
        w.terminar().expect("cerrar lote");
    }
    let t_esc = ahora().saturating_sub(t_esc0);

    // 2. Replicar al hub por QUIC.
    let cfg = lumen::quic::pinned_client_config(huella).expect("pin");
    let mut ep = lumen::quic::QuicEndpoint::client_with_config(Some(cfg)).expect("cliente");
    let t = ep.connect(addr).expect("conectar al hub");
    let mut znet = Znet::new();
    znet.init();
    let c = znet.connect("hub").expect("circuito");
    let mut qz = QuicZnet::new(t);

    let t_env0 = ahora();
    for h in &serie {
        let m = hechos_wire::mensaje_de_hecho(h);
        let _ = znet.reply(c, lumen_znet::ZnetReply::Data(m.body));
    }
    let enviados = qz.flush(&mut znet).expect("flush");
    // Marca de fin: el hub no puede distinguir "no hay datos aun" de "el barco
    // cerro", asi que se lo decimos explicitamente. Sin esto el hub espera a
    // ciegas o corta antes de hora.
    let _ = znet.reply(c, lumen_znet::ZnetReply::Data(b"FIN".to_vec()));
    let _ = qz.flush(&mut znet);
    let t_env = ahora().saturating_sub(t_env0);

    println!(
        "BARCO {} n={} escritos={} en {}ms · enviados={} en {}ms · clave={}",
        nombre, n, serie.len(), t_esc, enviados, t_env,
        &id.clave_publica_hex()[..16]
    );
}
