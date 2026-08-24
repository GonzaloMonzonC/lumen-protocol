//! M-Light compiler and resumable stack VM.
//!
//! The Rust VM owns language semantics, bytecode and execution state. Storage
//! remains behind [`host::Host`], so production integrations can keep SQLite
//! access inside `pdb_tools` instead of bypassing triggers and journals.

pub mod compiler;
pub mod compilation;
pub mod ffi;
pub mod host;
pub mod smith;
pub mod transpiler;
pub mod value;
pub mod vm;

#[cfg(feature = "wasm")]
pub mod wasm;

#[cfg(feature = "wasm")]
pub mod ddp;

pub use compiler::{Compiler, Instruction, Opcode, Program};
pub use host::{GlobalEntry, Host, MemoryHost};
pub use value::{Subscript, Value};
pub use vm::{Execution, LocalScope, LoopFrame, Vm, VmError, VmState, VM_VERSION};

/// Segundos desde UNIX epoch, portátil entre nativo y WASM.
///
/// En wasm32-unknown-unknown `std::time::SystemTime::now()` panica
/// ("time not implemented on this platform"), así que el reloj se obtiene
/// de JavaScript vía `Date.now()` (inyectado por wasm-bindgen). En nativo
/// usa SystemTime con fallback a 0.0.
pub fn time_now_secs() -> f64 {
    #[cfg(target_arch = "wasm32")]
    {
        js_now_secs()
    }
    #[cfg(not(target_arch = "wasm32"))]
    {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64()
    }
}

#[cfg(target_arch = "wasm32")]
#[wasm_bindgen::prelude::wasm_bindgen]
extern "C" {
    #[wasm_bindgen(js_name = Date)]
    fn js_date_now() -> f64;
}

#[cfg(target_arch = "wasm32")]
fn js_now_secs() -> f64 {
    // Date.now() devuelve milisegundos como entero
    js_date_now() / 1000.0
}
