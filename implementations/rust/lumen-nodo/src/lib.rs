//! `lumen-nodo` como librería: las piezas del nodo, usables desde tests y
//! desde otros binarios del ecosistema.
//!
//! El binario (`main.rs`) queda como capa fina de CLI sobre esto.

pub mod aplicar;
pub mod cadena;
pub mod carga;
pub mod descubrir;
pub mod destino;
pub mod entrada;
pub mod host_mvm;
pub mod identidad;
pub mod nodo;
pub mod profile;
pub mod replicacion;
