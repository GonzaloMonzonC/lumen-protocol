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
//!   lumen-nodo --set k=v ...                 override de perfil

mod aplicar;
mod carga;
mod destino;
mod host_mvm;
mod nodo;
mod profile;

use profile::{Profile, ProfileError, Storage};
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
        let Some(carga) = valor_posicional(&args) else {
            eprintln!("--enviar necesita la carga como argumento: \"^NS(k)=v\"");
            return ExitCode::from(FALLO_ARRANQUE);
        };
        return match enviar(&perfil, &addr, &carga) {
            Ok(msg) => {
                println!("respuesta: {}", msg);
                ExitCode::from(OK)
            }
            Err(e) => {
                eprintln!("FALLO al enviar: {e}");
                ExitCode::from(FALLO_ARRANQUE)
            }
        };
    }

    // ── Modo escucha ─────────────────────────────────────────────
    if quiere_escuchar {
        if !acepta_entrantes {
            eprintln!("NO ARRANCA: role=edge no acepta conexiones entrantes");
            return ExitCode::from(PERFIL_INVALIDO);
        }
        return escuchar(&perfil, &mut destino);
    }

    println!("nada que hacer: usa --escuchar o --enviar <addr> \"^NS(k)=v\"");
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
    println!("listo. Ctrl-C para parar.");

    let mut conexiones = 0usize;
    loop {
        match servidor.accept() {
            Ok(mut transporte) => {
                conexiones += 1;
                println!("--- conexion #{conexiones} aceptada ---");
                let mut log = |s: &str| println!("  {s}");
                let r = nodo::atender(&mut transporte, destino, &mut log);
                println!(
                    "--- conexion #{conexiones} cerrada: {} aplicados, {} fallidos, \
                     {} bytes, motivo: {} ---",
                    r.frames_aplicados, r.frames_fallidos, r.bytes_entrantes, r.cierre
                );
            }
            Err(e) => {
                eprintln!("error aceptando conexion: {e}");
                // Un accept que falla no debe tumbar el nodo: sigue escuchando.
                std::thread::sleep(std::time::Duration::from_millis(200));
            }
        }
    }
}

/// Manda una escritura a otro nodo y espera la respuesta.
fn enviar(perfil: &Profile, addr: &str, carga: &str) -> Result<String, String> {
    use lumen::frame::{self, ParseResult};
    use lumen::transport::Transport;
    use lumen_znet::{ddp_to_frame, frame_to_ddp, msg_type, DdpMessage};

    // Validar la carga ANTES de salir: no mandamos basura a la red.
    aplicar::parsear_set(carga.as_bytes()).map_err(|e| e.to_string())?;

    let mut cliente = nodo::conectar_como_cliente(perfil)?;
    let mut transporte = cliente.connect(addr).map_err(|e| format!("conectar {addr}: {e}"))?;

    let msg = DdpMessage::new(msg_type::DATA, 1, 1, 0, carga.as_bytes().to_vec());
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
        let m = transporte.read(&mut chunk).map_err(|e| format!("leer: {e}"))?;
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
    let con_valor = ["--pdb", "--set", "--almacen", "--enviar"];
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
  --pdb <ruta>            lee el perfil de ^SYS("NET",...) de esa PDB
  --almacen <ruta>        donde guarda el estado (fichero sqlite / dir lmdb)
  --set k=v               override de un campo del perfil (repetible)
  -h, --ayuda             esta ayuda

Campos: mode role discovery transport identity sign auth storage pin listen
Valores válidos (solo si el código existe):
  mode        lan | wan | offline
  role        hub | store | edge
  discovery   none | multicast* | seeds*
  transport   quic | shm
  identity    none | pin | pubkey*
  sign        none | hash-chain*
  auth        hmac | macaroon | dev
  storage     lmdb | sqlite
  pin         sha256 hex (64) del certificado del par, si identity=pin
  * = no implementado: el binario lo dice y NO arranca

Ejemplos:
  lumen-nodo --perfil --pdb pdb-data/lumen-pdb.db
  lumen-nodo --escuchar --almacen D:/nodo --set identity=pin --set pin=<hex>
  lumen-nodo --enviar 192.168.1.14:9443 "^FLOTA(BARCO,lat)=41.38"
"#
    );
}
