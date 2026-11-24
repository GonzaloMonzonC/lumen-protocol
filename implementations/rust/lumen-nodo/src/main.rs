//! `lumen-nodo` — un binario, varias filas (ADR-002).
//!
//! El nodo arranca leyendo su perfil de `^SYS("NET",...)` y **se niega a
//! arrancar** si el perfil pide algo que el binario no sabe hacer. No avisa y
//! sigue: no arranca. Esa es toda la diferencia entre una infraestructura y
//! una bandera decorativa.
//!
//! Uso:
//!   lumen-nodo --perfil            imprime el perfil resuelto y si arrancaría
//!   lumen-nodo --seco              valida y sale (no abre sockets)
//!   lumen-nodo --pdb <ruta>        siembra/lee de una PDB concreta
//!   lumen-nodo --set k=v ...       override de perfil por línea de comandos

mod carga;
mod profile;

use profile::{Profile, ProfileError};
use std::process::ExitCode;

/// Códigos de salida: distinguibles desde un script.
const OK: u8 = 0;
const PERFIL_INVALIDO: u8 = 3;
const NO_IMPLEMENTADO: u8 = 4;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();

    if args.iter().any(|a| a == "--ayuda" || a == "-h" || a == "--help") {
        imprimir_ayuda();
        return ExitCode::from(OK);
    }

    let mut perfil = profile::minimal_profile();

    // ── La PDB es la fuente de verdad; la CLI solo hace override ──
    let mut ruta_pdb: Option<String> = None;
    if let Some(pos) = args.iter().position(|a| a == "--pdb") {
        ruta_pdb = args.get(pos + 1).cloned();
    }
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

    if args.iter().any(|a| a == "--perfil" || a == "--seco") {
        return ExitCode::from(OK);
    }

    // ── Arranque real (solo el perfil mínimo, hoy) ───────────────
    eprintln!(
        "arranque real del nodo todavía no cableado: el perfil es válido y \
         el transporte QUIC está verificado en lumen-znet/tests/quic_e2e.rs"
    );
    ExitCode::from(OK)
}

fn imprimir_ayuda() {
    println!(
        r#"lumen-nodo — nodo LUMEN (ADR-002: un binario, varias filas)

  --perfil            imprime el perfil resuelto y los avisos
  --seco              valida el perfil y sale sin abrir sockets
  --set k=v           override de un campo del perfil (repetible)
  -h, --ayuda         esta ayuda

Campos: mode role discovery transport identity sign auth listen
Valores válidos (solo si el código existe):
  mode        lan | wan | offline
  role        hub | store | edge
  discovery   none | multicast* | seeds*
  transport   quic | shm
  identity    none | pin* | pubkey*
  sign        none | hash-chain*
  auth        hmac | macaroon | dev
  * = no implementado: el binario lo dice y NO arranca
"#
    );
}
