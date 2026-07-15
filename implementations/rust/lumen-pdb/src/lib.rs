//! lumen-pdb — engine de almacenamiento PDB sobre redb (Fase 4).
//!
//! Capas:
//!   subkey.rs  — codificación orden-preservante (golden vs Python)
//!   globals.rs — SET/GET/$ORDER/$DATA/KILL/$INCREMENT/MERGE
//!   host.rs    — RedbHost: trait Host de la VM M-Light sobre redb
//!   ffi.rs     — C ABI para el wrapper Python (lumen_pdb.py)

pub mod ffi;
pub mod globals;
pub mod host;
pub mod subkey;

pub use host::RedbHost;
