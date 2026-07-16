//! M-Light compiler and resumable stack VM.
//!
//! The Rust VM owns language semantics, bytecode and execution state. Storage
//! remains behind [`host::Host`], so production integrations can keep SQLite
//! access inside `pdb_tools` instead of bypassing triggers and journals.

pub mod compiler;
pub mod ffi;
pub mod host;
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
