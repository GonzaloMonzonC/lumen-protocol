/// Compilation Manager: transpila M → Rust → .dll y lo carga al vuelo.
///
/// Arquitectura:
///   1. Transpiler genera Rust para una rutina M
///   2. Se escribe como src/lib.rs en el workspace de compilación
///   3. `cargo build --release` produce un .dll
///   4. `libloading` carga el .dll y expone la función compilada
///   5. Fallback a intérprete si compilación falla
use crate::compiler::Program;
use crate::transpiler::transpile_to_rust;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Instant;

/// Compilation manager singleton
pub struct CompilationManager {
    /// Path to the compilation workspace (Cargo project)
    workspace_dir: PathBuf,
    /// Cache of loaded functions: routine_hash → function pointer
    cache: Mutex<HashMap<String, Box<dyn Fn() -> Result<i64, String> + Send + Sync>>>,
    /// Statistics
    pub stats: Mutex<CompilationStats>,
}

#[derive(Default, Clone, Debug)]
pub struct CompilationStats {
    pub total_compilations: u64,
    pub successful_compilations: u64,
    pub failed_compilations: u64,
    pub cache_hits: u64,
    pub total_compile_time_ms: u64,
}

impl CompilationManager {
    pub fn new(workspace_dir: &Path) -> Self {
        Self {
            workspace_dir: workspace_dir.to_path_buf(),
            cache: Mutex::new(HashMap::new()),
            stats: Mutex::new(CompilationStats::default()),
        }
    }

    /// Try to compile a program and return a loaded function.
    /// Returns None if compilation is not available or fails.
    pub fn try_compile(&self, program: &Program, name: &str) -> Option<Box<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        let hash = format!("{}:{}", name, program.source_hash);
        
        // Check cache (stat only — Arc-based cache would be needed for real reuse)
        // For now, just track cache hit stats. Real cache returning would need Arc.
        {
            let c = self.cache.lock().unwrap();
            self.stats.lock().unwrap().cache_hits += if c.contains_key(&hash) { 1 } else { 0 };
        }
        
        // Transpile M → Rust
        let rust_code = transpile_to_rust(program, name);
        
        // Write to workspace
        let lib_rs = self.workspace_dir.join("src").join("lib.rs");
        if let Err(e) = std::fs::write(&lib_rs, &rust_code) {
            eprintln!("CompilationManager: failed to write lib.rs: {}", e);
            self.stats.lock().unwrap().failed_compilations += 1;
            return None;
        }
        
        // Build
        let t0 = Instant::now();
        let output = std::process::Command::new("cargo")
            .args(["build", "--release", "--manifest-path"])
            .arg(self.workspace_dir.join("Cargo.toml"))
            .output();
        
        let compile_time = t0.elapsed().as_millis() as u64;
        self.stats.lock().unwrap().total_compile_time_ms += compile_time;
        self.stats.lock().unwrap().total_compilations += 1;
        
        match output {
            Ok(out) if out.status.success() => {
                // Load the .dll
                let dll_name = if cfg!(target_os = "windows") {
                    "m_compiled.dll"
                } else if cfg!(target_os = "macos") {
                    "libm_compiled.dylib"
                } else {
                    "libm_compiled.so"
                };
                let dll_path = self.workspace_dir.join("target").join("release").join(dll_name);
                
                match self.load_function(&dll_path, name) {
                    Some(f) => {
                        self.stats.lock().unwrap().successful_compilations += 1;
                        self.cache.lock().unwrap().insert(hash, /* store */ f);
                        // Reacquire from cache
                        None // TODO: return the loaded function properly
                    }
                    None => {
                        self.stats.lock().unwrap().failed_compilations += 1;
                        None
                    }
                }
            }
            _ => {
                self.stats.lock().unwrap().failed_compilations += 1;
                None
            }
        }
    }
    
    /// Load a function from a .dll
    fn load_function(&self, dll_path: &Path, fn_name: &str) -> Option<Box<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        // Safety: we control the .dll we generated
        unsafe {
            match libloading::Library::new(dll_path) {
                Ok(lib) => {
                    let func: libloading::Symbol<extern "C" fn(i64) -> i64> = match lib.get(fn_name.as_bytes()) {
                        Ok(f) => f,
                        Err(e) => {
                            eprintln!("CompilationManager: symbol '{}' not found: {}", fn_name, e);
                            // Leak the library so it stays loaded (simplification)
                            std::mem::forget(lib);
                            return None;
                        }
                    };
                    let func_ptr = func.into_raw();
                    std::mem::forget(lib); // Keep library loaded
                    
                    let closure = move || -> Result<i64, String> {
                        let result = func_ptr(i64::default());
                        Ok(result)
                    };
                    Some(Box::new(closure))
                }
                Err(e) => {
                    eprintln!("CompilationManager: failed to load {}: {}", dll_path.display(), e);
                    None
                }
            }
        }
    }
    
    /// Try to compile by routine name and source
    pub fn try_compile_routine(&self, name: &str, source: &str) -> Option<Box<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        let program = match crate::compiler::Compiler::compile(source) {
            Ok(p) => p,
            Err(e) => {
                eprintln!("JIT: compile error for '{}': {}", name, e);
                return None;
            }
        };
        self.try_compile(&program, name)
    }
    
    /// Get compilation statistics
    pub fn get_stats(&self) -> CompilationStats {
        self.stats.lock().unwrap().clone()
    }
}

/// Generate the initial lib.rs for the workspace with default function
pub fn generate_default_lib_rs() -> String {
    r#"use lumen_mlight::*;

#[no_mangle]
pub extern "C" fn compiled_routine(input: i64) -> i64 {
    let mut x = input as f64;
    x = x + 1.0;
    x as i64
}
"#.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_workspace_exists() {
        let manager = CompilationManager::new(
            &PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("compiled_workspace")
        );
        assert!(manager.workspace_dir.exists(), "Workspace should exist");
        assert!(manager.workspace_dir.join("Cargo.toml").exists(), "Cargo.toml should exist");
    }
}
