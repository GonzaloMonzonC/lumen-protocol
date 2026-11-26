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

    // UN SOLO host para todo el hub.
    //
    // LMDB no admite el mismo entorno abierto dos veces en un proceso: si cada
    // hilo abre el suyo, se quedan esperandose y el hub se CUELGA. Por eso el
    // host vive en el hilo principal y los hilos de red le pasan los hechos por
    // un canal. Asi la RAM del hub no crece con el volumen: cada lote se guarda
    // y se suelta.
    let mut host = lumen_mlight::MemoryHost::from_lmdb_con_durabilidad(&dir, true)
        .expect("lmdb hub");

    let t0 = ahora();
    let mut total_aceptados = 0usize;
    let mut total_rechazados = 0usize;
    let mut total_conflictos = 0usize;
    let mut barcos = 0usize;

    // Un canal por conexion, guardado junto a su hilo.
    let mut pendientes: Vec<(std::thread::JoinHandle<(usize, Option<String>)>,
                             std::sync::mpsc::Receiver<Vec<lumen_znet::DdpMessage>>)> = Vec::new();

    while barcos < esperados {
        // aceptar_conexion() vuelve en cuanto termina el handshake, SIN esperar
        // al primer stream. Con accept() el hub se quedaba clavado esperando
        // datos de un barco mientras los demas recibian ConnectionRefused.
        let conexion = match ep.aceptar_conexion() {
            Ok(t) => t,
            Err(e) => {
                eprintln!("accept: {e:?}");
                break;
            }
        };
        barcos += 1;

        let (tx, rx) = std::sync::mpsc::channel::<Vec<lumen_znet::DdpMessage>>();
        let mut t = conexion;
        let hilo = std::thread::spawn(move || -> (usize, Option<String>) {
            let mut znet = Znet::new();
            znet.init();
            if let Err(e) = t.aceptar_stream() {
                eprintln!("stream: {e:?}");
            }
            let mut qz = QuicZnet::new(t);
            let mut lote: Vec<lumen_znet::DdpMessage> = Vec::new();
            let mut recibidos = 0usize;
            let mut error: Option<String> = None;

            // Antes habia un contador `sin_datos` que cortaba a las 6000 vueltas
            // sin datos. Era una HEURISTICA para adivinar el cierre, y con
            // volumen alto cortaba conexiones vivas.
            //
            // Ahora `poll_estado` distingue Vacio de Cerrado: se drena mientras
            // la conexion viva, y se para SOLO cuando el par cierra de verdad.
            let mut vueltas_vacias = 0u32;
            loop {
                // Primero enviar lo pendiente (el hub responde ACK por ventana).
                let _ = qz.flush(&mut znet);
                let lectura = match qz.poll_estado(&mut znet) {
                    Ok(l) => l,
                    Err(e) => {
                        error = Some(format!("{e:?}"));
                        break;
                    }
                };
                match lectura {
                    lumen_znet::Lectura::Cerrado => break,
                    lumen_znet::Lectura::Vacio => {
                        // Sin datos AHORA, pero la conexion vive. Se espera un
                        // poco para no girar en vacio, sin limite de vueltas:
                        // el FIN del barco o el cierre del stream deciden.
                        vueltas_vacias += 1;
                        std::thread::sleep(std::time::Duration::from_millis(2));
                        // Red de seguridad anti-bloqueo: 60 s sin nada.
                        if vueltas_vacias > 30_000 {
                            error = Some("60 s sin datos ni cierre".into());
                            break;
                        }
                    }
                    lumen_znet::Lectura::Datos(_) => {
                        vueltas_vacias = 0;
                    }
                }
                let mut fin = false;
                // Drenar TODA la cola antes de mirar FIN: si se corta al verlo,
                // los del mismo lote detras de el se pierden en silencio.
                while let Some(m) = znet.recv() {
                    if m.body.as_slice() == b"FIN" {
                        fin = true;
                        continue;
                    }
                    lote.push(m);
                }
                // Volcar al hilo principal y vaciar: la RAM del hilo no crece.
                if !lote.is_empty() {
                    recibidos += lote.len();
                    if tx.send(std::mem::take(&mut lote)).is_err() {
                        break;
                    }
                    lote = Vec::new();
                    // ACK POR VENTANA: el barco espera esto antes de mandar la
                    // siguiente. Sin ACK por lote, el emisor llena la ventana de
                    // QUIC y se bloquea, y el hub nunca termina de leer.
                    let ack = format!("ACK {recibidos}").into_bytes();
                    let _ = znet.reply(0u16, lumen_znet::ZnetReply::Data(ack));
                    if qz.flush(&mut znet).is_err() {
                        break;
                    }
                }
                if fin {
                    break;
                }
            }

            // ACK: el barco espera esto antes de cerrar. Sin el, su proceso
            // termina y se pierden los hechos que aun no se habian leido.
            let ack = format!("ACK {recibidos}").into_bytes();
            let _ = znet.reply(0u16, lumen_znet::ZnetReply::Data(ack));
            let _ = qz.flush(&mut znet);
            (recibidos, error)
        });

        // NO se espera aqui: esperar convertiria el bucle en secuencial.
        pendientes.push((hilo, rx));

    }

    // Recoger: guardar lo que cada conexion mando, sin acumular todo en RAM.
    for (n, (hilo, rx)) in pendientes.into_iter().enumerate() {
        let (recibidos, error) = hilo.join().unwrap_or((0, Some("hilo murio".into())));
        let mut aceptados = 0usize;
        let mut rechazados = 0usize;
        let mut conflictos = 0usize;
        let mut motivo: Option<String> = None;
        let mut detalle_real: Option<String> = None;
        while let Ok(lote) = rx.recv() {
            let r = hechos_wire::recibir_hechos(&mut host, &lote, None);
            aceptados += r.aceptados;
            rechazados += r.rechazados;
            conflictos += r.conflictos;
            if motivo.is_none() {
                motivo = r.primer_motivo.clone();
            }
            // El primer rechazo real, con su mensaje completo de LMDB.
            if r.rechazados > 0 && detalle_real.is_none() {
                detalle_real = r.primer_motivo.clone();
            }
        }
        total_aceptados += aceptados;
        total_rechazados += rechazados;
        total_conflictos += conflictos;
        println!(
            "BARCO {} recibidos={} aceptados={} rechazados={} conflictos={}{}",
            n + 1, recibidos, aceptados, rechazados, conflictos,
            match (error, detalle_real, motivo) {
                (Some(e), _, _) => format!(" error={e}"),
                (None, Some(d), _) => format!(" motivo={d}"),
                (None, None, Some(m)) => format!(" motivo={m}"),
                _ => String::new(),
            }
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
    // El perfil decide el MAPSIZE: ya no hay dos fuentes de verdad.
    perfil.aplicar_al_entorno();

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

    // 2. Replicar al hub por QUIC, EN VENTANAS.
    //
    // ## Por que en ventanas y no todo de golpe
    //
    // La version anterior hacia un `flush` con los N hechos: `write_all` de
    // ~1,5 MB en un stream. QUIC tiene ventana de flujo limitada, asi que
    // `write_all` **se bloquea** esperando credito que solo llega si el hub lee.
    // Y el hub lee 8 KB por ciclo con 2 hilos de runtime: con 20 conexiones a la
    // vez, se serializan.
    //
    // Medido: 20 barcos x 12.000 -> 177.709 de 240.000 (62.291 perdidos).
    //
    // Ahora se manda en ventanas de 256, esperando el ACK de cada una. El flujo
    // nunca se llena y ninguna parte se queda bloqueada esperando a la otra.
    // Es el patron que coincidieron Poli y Zalo: **estreamear en lotes, ACK por
    // lote, nunca uno global al final**.
    const VENTANA: usize = 256;

    let cfg = lumen::quic::pinned_client_config(huella).expect("pin");
    let mut ep = lumen::quic::QuicEndpoint::client_with_config(Some(cfg)).expect("cliente");
    let t = ep.connect(addr).expect("conectar al hub");
    let mut znet = Znet::new();
    znet.init();
    let c = znet.connect("hub").expect("circuito");
    let mut qz = QuicZnet::new(t);

    let t_env0 = ahora();
    let mut enviados = 0usize;
    let mut fallo_flujo: Option<String> = None;

    for trozo in serie.chunks(VENTANA) {
        for h in trozo {
            let m = hechos_wire::mensaje_de_hecho(h);
            let _ = znet.reply(c, lumen_znet::ZnetReply::Data(m.body));
        }
        // Flush de la ventana: a lo sumo 256 mensajes (~32 KB). Cabe en la
        // ventana de QUIC sin bloquearse.
        match qz.flush(&mut znet) {
            Ok(n) => enviados += n,
            Err(e) => {
                fallo_flujo = Some(format!("flush: {e:?}"));
                break;
            }
        }

        // Esperar el ACK de ESTA ventana antes de mandar la siguiente.
        let objetivo = format!("ACK {enviados}");
        let mut espera = 0;
        let mut confirmado = false;
        while espera < 20000 {
            match qz.pump(&mut znet) {
                Ok((_e, recibidos)) => {
                    if recibidos > 0 {
                        while let Some(m) = znet.recv() {
                            if m.body.as_slice() == objetivo.as_bytes() {
                                confirmado = true;
                            }
                        }
                    }
                }
                Err(e) => {
                    fallo_flujo = Some(format!("pump: {e:?}"));
                    break;
                }
            }
            if confirmado || fallo_flujo.is_some() {
                break;
            }
            espera += 1;
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
        if !confirmado {
            fallo_flujo = Some(format!(
                "sin ACK de la ventana tras {enviados} enviados"
            ));
            break;
        }
    }

    // FIN explicito: el hub lo necesita para saber que no vienen mas.
    let _ = znet.reply(c, lumen_znet::ZnetReply::Data(b"FIN".to_vec()));
    let _ = qz.flush(&mut znet);
    let t_env = ahora().saturating_sub(t_env0);

    if let Some(f) = &fallo_flujo {
        eprintln!("aviso: {f}");
    }
    println!(
        "BARCO {} n={} escritos={} en {}ms · enviados={} en {}ms · clave={}{}",
        nombre, n, serie.len(), t_esc, enviados, t_env,
        &id.clave_publica_hex()[..16],
        match &fallo_flujo {
            Some(f) => format!(" · INCOMPLETO: {f}"),
            None => String::new(),
        }
    );
}
