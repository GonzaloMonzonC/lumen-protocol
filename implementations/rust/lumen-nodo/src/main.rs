//! `lumen-nodo` — un binario, varias filas (ADR-002).
//!
//! El nodo arranca leyendo su perfil de `^SYS("NET",...)` y **se niega a
//! arrancar** si el perfil pide algo que el binario no sabe hacer. No avisa y
//! sigue: no arranca. Esa es toda la diferencia entre una infraestructura y
//! una bandera decorativa.
//!
//! Uso:
//!   lumen-nodo --perfil                      imprime el perfil resuelto
//!   lumen-nodo --seco                        valida y sale (no abre sockets)
//!   lumen-nodo --pdb <ruta> --almacen <ruta> sirve con una PDB/entorno dados
//!   lumen-nodo --escuchar                    arranca el nodo (escucha y aplica)
//!   lumen-nodo --enviar <addr> "^NS(k)=v"    manda una escritura a otro nodo
//!   lumen-nodo --verificar --serie "^NS(k)"  verifica la cadena de una serie
//!   lumen-nodo --set k=v ...                 override de perfil

use lumen_nodo_lib::profile::{self, Profile, ProfileError, Storage};
use lumen_nodo_lib::{aplicar, cadena, carga, descubrir, host_mvm, nodo};
use std::process::ExitCode;

/// Códigos de salida: distinguibles desde un script.
const OK: u8 = 0;
const PERFIL_INVALIDO: u8 = 3;
const NO_IMPLEMENTADO: u8 = 4;
const FALLO_ARRANQUE: u8 = 5;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();

    if args.iter().any(|a| a == "--ayuda" || a == "-h" || a == "--help") {
        imprimir_ayuda();
        return ExitCode::from(OK);
    }

    let mut perfil = profile::minimal_profile();

    // ── La PDB es la fuente de verdad; la CLI solo hace override ──
    let ruta_pdb = valor_de(&args, "--pdb");
    #[cfg(feature = "pdb")]
    if let Some(ref ruta) = ruta_pdb {
        match carga::leer_de_sqlite(ruta) {
            Ok(campos) => {
                let c = carga::cargar(|k| {
                    campos
                        .iter()
                        .find(|(kk, _)| kk == k)
                        .map(|(_, v)| v.clone())
                });
                perfil = c.perfil;
                if !c.desde_pdb.is_empty() {
                    println!("perfil leido de PDB: {}", c.desde_pdb.join(" "));
                }
                if let Some(f) = c.fallo {
                    println!("AVISO: campos ignorados de la PDB: {f}");
                }
            }
            Err(e) => {
                println!("AVISO: no se pudo leer la PDB ({e}); usando perfil minimo");
            }
        }
    }
    #[cfg(not(feature = "pdb"))]
    if ruta_pdb.is_some() {
        println!("AVISO: binario compilado sin feature 'pdb'; --pdb ignorado");
    }

    // Overrides por línea de comandos: `--set mode=lan --set identity=pin`
    let mut i = 0;
    while i < args.len() {
        if args[i] == "--set" {
            let Some(kv) = args.get(i + 1) else {
                eprintln!("--set necesita k=v");
                return ExitCode::from(PERFIL_INVALIDO);
            };
            let (k, v) = match kv.split_once('=') {
                Some(x) => x,
                None => {
                    eprintln!("--set espera k=v, recibido: {kv}");
                    return ExitCode::from(PERFIL_INVALIDO);
                }
            };
            if let Err(e) = perfil.set_field(k, v) {
                eprintln!("ERROR: {e}");
                return ExitCode::from(PERFIL_INVALIDO);
            }
            i += 2;
            continue;
        }
        i += 1;
    }

    // ── El perfil resuelto, siempre visible ───────────────────────
    println!("lumen-nodo {}", env!("CARGO_PKG_VERSION"));
    println!("perfil: {}", perfil.describe());

    for aviso in perfil.warnings() {
        println!("AVISO: {aviso}");
    }

    // ── La validación: antes de abrir ningún socket ───────────────
    match perfil.validate() {
        Ok(()) => println!("perfil: VALIDO"),
        Err(e @ ProfileError::NotImplemented { .. }) => {
            eprintln!("NO ARRANCA: {e}");
            eprintln!("(ADR-002: un valor sin código y sin test no es una opción)");
            return ExitCode::from(NO_IMPLEMENTADO);
        }
        Err(e) => {
            eprintln!("NO ARRANCA: {e}");
            return ExitCode::from(PERFIL_INVALIDO);
        }
    }

    let quiere_escuchar = args.iter().any(|a| a == "--escuchar");
    let destino_envio = valor_de(&args, "--enviar");
    let quiere_verificar = args.iter().any(|a| a == "--verificar");

    if args.iter().any(|a| a == "--perfil" || a == "--seco") && !quiere_escuchar {
        return ExitCode::from(OK);
    }

    // ── Dónde se guarda el estado ─────────────────────────────────
    // sqlite trabaja sobre un fichero; lmdb sobre un DIRECTORIO (data.mdb +
    // lock.mdb). Confundirlos es el error clásico, así que se resuelve aquí
    // y se imprime lo que se va a usar.
    let (ruta_estado, origen) = match (valor_de(&args, "--almacen"), ruta_pdb.clone()) {
        (Some(a), _) => (a, "--almacen"),
        (None, Some(p)) => (p, "--pdb"),
        (None, None) => {
            eprintln!("falta --almacen <ruta>: sin sitio donde guardar, el nodo no sirve");
            return ExitCode::from(FALLO_ARRANQUE);
        }
    };
    println!(
        "almacen: {} ({}) -> {}",
        match perfil.storage {
            Storage::Sqlite => "sqlite",
            Storage::Lmdb => "lmdb",
        },
        origen,
        ruta_estado
    );

    // Rol: `edge` conecta hacia afuera y no acepta entrantes; `hub`/`store` sí.
    let acepta_entrantes = perfil.role != profile::Role::Edge;
    let solo_lectura = perfil.mode == profile::Mode::Offline;

    let mut destino = match host_mvm::DestinoMvm::abrir(&ruta_estado, perfil.storage, solo_lectura)
    {
        Ok(d) => d,
        Err(e) => {
            eprintln!("NO ARRANCA: {e}");
            return ExitCode::from(FALLO_ARRANQUE);
        }
    };

    // ── Modo envío: una escritura a otro nodo ────────────────────
    if let Some(addr) = destino_envio {
        let Some(carga_txt) = valor_posicional(&args) else {
            eprintln!("--enviar necesita la carga como argumento: \"^NS(k)=v\"");
            return ExitCode::from(FALLO_ARRANQUE);
        };
        return match enviar(&perfil, &addr, &carga_txt) {
            Ok(msg) => {
                println!("respuesta: {msg}");
                ExitCode::from(OK)
            }
            Err(e) => {
                eprintln!("FALLO al enviar: {e}");
                ExitCode::from(FALLO_ARRANQUE)
            }
        };
    }

    // ── Modo verificar: comprobar la cadena de una serie ─────────
    if quiere_verificar {
        return verificar_cadena(&destino, &args);
    }

    // ── Modo escucha ─────────────────────────────────────────────
    if quiere_escuchar {
        if !acepta_entrantes {
            eprintln!("NO ARRANCA: role=edge no acepta conexiones entrantes");
            return ExitCode::from(PERFIL_INVALIDO);
        }
        return escuchar(&perfil, &mut destino);
    }

    println!("nada que hacer: usa --escuchar, --enviar <addr> \"^NS(k)=v\" o --verificar");
    ExitCode::from(OK)
}

/// Arranca el nodo servidor: escucha y aplica lo que llega.
fn escuchar(perfil: &Profile, destino: &mut host_mvm::DestinoMvm) -> ExitCode {
    let (mut servidor, huella) = match nodo::escuchar(perfil, perfil.pin.as_deref()) {
        Ok(x) => x,
        Err(e) => {
            eprintln!("NO ARRANCA: {e}");
            return ExitCode::from(FALLO_ARRANQUE);
        }
    };
    let addr = servidor
        .local_addr()
        .map(|a| a.to_string())
        .unwrap_or_else(|_| "?".into());

    println!("ESCUCHANDO en {addr} (udp/quic)");
    println!("huella de mi certificado: {huella}");
    println!("  fija esta huella en el nodo contrario:");
    println!("  ^SYS(\"NET\",\"pin\")=\"{huella}\"  con identity=pin");

    // ── Descubrimiento: anunciar y escuchar en la LAN ─────────────
    // Se abre DESPUÉS de tener la huella: el anuncio la lleva, y ese es el
    // motivo de que el descubrimiento sirva para algo (sin huella, descubrir
    // un nodo es descubrir un desconocido al que aceptar a ciegas).
    let mut descubrimiento = if perfil.discovery == profile::Discovery::Multicast {
        let iface = perfil.interface.clone().unwrap_or_default();
        match descubrir::Descubrimiento::unirse(&perfil.grupo, &iface) {
            Ok(d) => {
                println!(
                    "DESCUBRIMIENTO: grupo {} por interfaz {}",
                    perfil.grupo, iface
                );
                let anuncio = descubrir::Anuncio {
                    version: descubrir::VERSION_ANUNCIO,
                    role: formato_rol(perfil.role).to_string(),
                    quic: servidor
                        .local_addr()
                        .unwrap_or_else(|_| "0.0.0.0:0".parse().unwrap()),
                    huella: huella.clone(),
                };
                match d.anunciar(&anuncio) {
                    Ok(n) => println!("anuncio emitido ({n} bytes)"),
                    Err(e) => println!("AVISO: no se pudo anunciar: {e}"),
                }
                Some(d)
            }
            Err(e) => {
                // Un fallo de descubrimiento NO tumba el nodo: sigue
                // escuchando por si alguien le da la dirección a mano.
                println!("AVISO: descubrimiento no disponible ({e}); sigo escuchando");
                None
            }
        }
    } else {
        println!("DESCUBRIMIENTO: desactivado (discovery=none) — habrá que dar la dirección a mano");
        None
    };

    println!("listo. Ctrl-C para parar.");

    let firmar = perfil.sign == profile::Sign::HashChain;
    if firmar {
        println!("CADENA: sign=hash-chain activo (valor|prev|hash, sello cada 100)");
    }

    let mut conexiones = 0usize;
    let mut pares_vistos: Vec<String> = Vec::new();
    let mut ultimo_anuncio = std::time::Instant::now();

    loop {
        // ── Anunciar periódicamente y recoger pares ───────────────
        if let Some(ref mut d) = descubrimiento {
            // Re-anunciar cada 10 s: un nodo que arranca después nos encuentra.
            if ultimo_anuncio.elapsed() > std::time::Duration::from_secs(10) {
                let anuncio = descubrir::Anuncio {
                    version: descubrir::VERSION_ANUNCIO,
                    role: formato_rol(perfil.role).to_string(),
                    quic: servidor
                        .local_addr()
                        .unwrap_or_else(|_| "0.0.0.0:0".parse().unwrap()),
                    huella: huella.clone(),
                };
                let _ = d.anunciar(&anuncio);
                ultimo_anuncio = std::time::Instant::now();
            }
            match d.recibir() {
                Ok(Some((a, origen))) => {
                    if descubrir::es_propio(&a, &huella) {
                        // Es nuestro propio anuncio (loopback multicast).
                    } else {
                        let firma = format!("{}|{}", a.quic, a.huella);
                        if !pares_vistos.contains(&firma) {
                            println!("--- PAR DESCUBIERTO (desde {origen}) ---");
                            println!("  escucha en: {}", a.quic);
                            println!("  rol: {}", a.role);
                            println!("  huella: {}", a.huella);
                            println!("  para hablarle con identidad verificada:");
                            println!("  lumen-nodo --enviar {} \"^NS(k)=v\" \\", a.quic);
                            println!("    --set identity=pin --set pin={}", a.huella);
                            pares_vistos.push(firma);
                        }
                    }
                }
                Ok(None) => {}
                Err(e) => println!("AVISO: error leyendo anuncios: {e}"),
            }
        }

        // ── Aceptar conexiones (con timeout corto para no bloquear
        //    el bucle de anuncios) ──────────────────────────────────
        match servidor.aceptar_con_timeout(std::time::Duration::from_millis(200)) {
            Ok(Some(mut transporte)) => {
                conexiones += 1;
                println!("--- conexion #{conexiones} aceptada ---");
                let mut log = |s: &str| println!("  {s}");
                let r = nodo::atender(&mut transporte, destino, firmar, &mut log);
                println!(
                    "--- conexion #{conexiones} cerrada: {} aplicados, {} fallidos, \
                     {} bytes, motivo: {} ---",
                    r.frames_aplicados, r.frames_fallidos, r.bytes_entrantes, r.cierre
                );
            }
            Ok(None) => {}
            Err(e) => {
                eprintln!("AVISO aceptando conexion: {e}");
                std::thread::sleep(std::time::Duration::from_millis(200));
            }
        }
    }
}

/// El rol como texto para el anuncio.
fn formato_rol(rol: profile::Role) -> &'static str {
    match rol {
        profile::Role::Hub => "hub",
        profile::Role::Store => "store",
        profile::Role::Edge => "edge",
    }
}

/// Verifica la cadena de una serie leída de la PDB.
///
/// Uso: `--verificar --serie "^FLOTA(BARCO,lat)"`
fn verificar_cadena(destino: &host_mvm::DestinoMvm, args: &[String]) -> ExitCode {
    let Some(serie) = valor_de(args, "--serie") else {
        eprintln!("--verificar necesita --serie \"^NS(clave,campo)\" (sin el numero)");
        return ExitCode::from(FALLO_ARRANQUE);
    };
    let serie = serie.trim().trim_start_matches('^').to_string();
    let (ns, resto) = match serie.split_once('(') {
        Some((n, r)) => (n.to_string(), r.trim_end_matches(')').to_string()),
        None => {
            eprintln!("--serie debe tener forma ^NS(clave,campo)");
            return ExitCode::from(FALLO_ARRANQUE);
        }
    };
    let clave: Vec<String> = if resto.trim().is_empty() {
        Vec::new()
    } else {
        resto.split(',').map(|s| s.trim().to_string()).collect()
    };

    // Recorrer 1..N. La serie puede empezar en 1; se corta tras dos ausencias
    // consecutivas (el final de la serie).
    let mut muestras: Vec<(u64, String)> = Vec::new();
    let mut huecos = 0u32;
    for n in 1u64..=1_000_000 {
        let mut subs = clave.clone();
        subs.push(n.to_string());
        match destino.leer(&ns, &subs) {
            Some(v) => {
                muestras.push((n, v));
                huecos = 0;
            }
            None => {
                if muestras.is_empty() {
                    if n > 1000 {
                        break;
                    }
                } else {
                    huecos += 1;
                    if huecos >= 2 {
                        break;
                    }
                }
            }
        }
    }

    if muestras.is_empty() {
        println!("serie ^{ns}({}) vacia o inexistente", clave.join(","));
        return ExitCode::from(OK);
    }

    println!(
        "verificando ^{ns}({}) — {} muestras leidas (n={}..{})",
        clave.join(","),
        muestras.len(),
        muestras.first().map(|(n, _)| *n).unwrap_or(0),
        muestras.last().map(|(n, _)| *n).unwrap_or(0)
    );

    match cadena::verificar(&muestras).problema {
        None => {
            let v = cadena::verificar(&muestras);
            println!(
                "RESULTADO: INTEGRA — {} muestras en cadena, {} sellos de bloque",
                v.muestras_ok, v.sellos_ok
            );
            ExitCode::from(OK)
        }
        Some(p) => {
            println!("RESULTADO: ROTA");
            println!("  {p}");
            ExitCode::from(FALLO_ARRANQUE)
        }
    }
}

/// Manda una escritura a otro nodo y espera la respuesta.
fn enviar(perfil: &Profile, addr: &str, carga_txt: &str) -> Result<String, String> {
    use lumen::frame::{self, ParseResult};
    use lumen::transport::Transport;
    use lumen_znet::{ddp_to_frame, frame_to_ddp, msg_type, DdpMessage};

    // Validar la carga ANTES de salir: no mandamos basura a la red.
    aplicar::parsear_set(carga_txt.as_bytes()).map_err(|e| e.to_string())?;

    let mut cliente = nodo::conectar_como_cliente(perfil)?;
    let mut transporte = cliente
        .connect(addr)
        .map_err(|e| format!("conectar {addr}: {e}"))?;

    let msg = DdpMessage::new(msg_type::DATA, 1, 1, 0, carga_txt.as_bytes().to_vec());
    let (ft, fl, p) = ddp_to_frame(&msg);
    let mut out = vec![0u8; frame::build_size(p.len())];
    let n = frame::build(ft, fl, &p, &mut out);
    transporte
        .write_all(&out[..n])
        .and_then(|_| transporte.flush())
        .map_err(|e| format!("escribir: {e}"))?;

    // Esperar la respuesta.
    let mut buf = Vec::new();
    let inicio = std::time::Instant::now();
    loop {
        if inicio.elapsed() > std::time::Duration::from_secs(15) {
            return Err("timeout esperando respuesta".into());
        }
        let mut chunk = [0u8; 4096];
        let m = transporte
            .read(&mut chunk)
            .map_err(|e| format!("leer: {e}"))?;
        if m == 0 {
            return Err("el par cerro antes de responder".into());
        }
        buf.extend_from_slice(&chunk[..m]);
        if let ParseResult::Complete { frame, .. } = frame::parse(&buf) {
            let r = frame_to_ddp(frame.frame_type, frame.payload)
                .map_err(|e| format!("respuesta no es DDP: {e}"))?;
            return match r.kind {
                msg_type::SUCCESS => Ok("SUCCESS (aplicado por el par)".into()),
                msg_type::FAILURE => Ok(format!(
                    "FAILURE (rechazado): {}",
                    String::from_utf8_lossy(&r.body)
                )),
                msg_type::EMPTY => Ok("EMPTY (frame ignorado)".into()),
                other => Ok(format!("tipo 0x{other:02x}")),
            };
        }
    }
}

/// Valor de un `--flag <valor>`.
fn valor_de(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|p| args.get(p + 1))
        .cloned()
}

/// Primer argumento que no empieza por `--` y no es valor de otro flag.
fn valor_posicional(args: &[String]) -> Option<String> {
    let con_valor = ["--pdb", "--set", "--almacen", "--enviar", "--serie"];
    let mut i = 0;
    while i < args.len() {
        let a = &args[i];
        if con_valor.contains(&a.as_str()) {
            i += 2;
            continue;
        }
        if !a.starts_with("--") {
            return Some(a.clone());
        }
        i += 1;
    }
    None
}

fn imprimir_ayuda() {
    println!(
        r#"lumen-nodo — nodo LUMEN (ADR-002: un binario, varias filas)

  --perfil                imprime el perfil resuelto y los avisos
  --seco                  valida el perfil y sale sin abrir sockets
  --escuchar              arranca el nodo: escucha y aplica lo que llega
  --enviar <addr> "<set>" manda una escritura a otro nodo y espera respuesta
  --verificar             verifica la cadena de una serie (con --serie)
  --serie "^NS(clave)"    serie a verificar, sin el numero de muestra
  --pdb <ruta>            lee el perfil de ^SYS("NET",...) de esa PDB
  --almacen <ruta>        donde guarda el estado (fichero sqlite / dir lmdb)
  --set k=v               override de un campo del perfil (repetible)
  -h, --ayuda             esta ayuda

Campos: mode role discovery transport identity sign auth storage pin listen interface grupo
Valores válidos (solo si el código existe):
  mode        lan | wan | offline
  role        hub | store | edge
  discovery   none | multicast | seeds*
  transport   quic | shm
  identity    none | pin | pubkey*
  sign        none | hash-chain
  auth        hmac | macaroon | dev
  storage     lmdb | sqlite
  pin         sha256 hex (64) del certificado del par, si identity=pin
  interface   IPv4 local por la que anunciar (requerido si discovery=multicast)
  * = no implementado: el binario lo dice y NO arranca

Ejemplos:
  lumen-nodo --perfil --pdb pdb-data/lumen-pdb.db
  lumen-nodo --escuchar --almacen D:/nodo --set identity=pin --set pin=<hex>
  lumen-nodo --escuchar --almacen D:/nodo --set sign=hash-chain
  lumen-nodo --enviar 192.168.1.14:9443 "^FLOTA(BARCO,lat,1)=41.38"
  lumen-nodo --verificar --serie "^FLOTA(BARCO,lat)" --almacen D:/nodo
"#
    );
}
