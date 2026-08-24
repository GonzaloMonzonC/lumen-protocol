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
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Instant;

/// Compilation manager singleton
pub struct CompilationManager {
    /// Path to the compilation workspace (Cargo project)
    workspace_dir: PathBuf,
    /// Cache directory for compiled .dlls (persists across restarts)
    cache_dir: PathBuf,
    /// Compiled functions by name (Arc for cloneability)
    fn_cache: Mutex<HashMap<String, Arc<dyn Fn() -> Result<i64, String> + Send + Sync>>>,
    /// Call counters for hot-path detection: routine_name → call_count
    call_counts: Mutex<HashMap<String, u32>>,
    /// Number of calls before auto-compilation triggers (default: 3)
    hot_threshold: u32,
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
        let cache_dir = workspace_dir.parent()
            .map(|p| p.join("compiled_cache"))
            .unwrap_or_else(|| PathBuf::from("compiled_cache"));
        let _ = fs::create_dir_all(&cache_dir); // Ignore if exists
        Self {
            workspace_dir: workspace_dir.to_path_buf(),
            cache_dir,
            fn_cache: Mutex::new(HashMap::new()),
            call_counts: Mutex::new(HashMap::new()),
            hot_threshold: 3,
            stats: Mutex::new(CompilationStats::default()),
        }
    }
    
    /// Compute cache key for a routine
    fn cache_key(name: &str, source: &str) -> String {
        use std::hash::{Hash, Hasher};
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        source.hash(&mut hasher);
        format!("{}_{:x}", name, hasher.finish())
    }
    
    /// Path to cached .dll for a given cache key
    fn cached_dll_path(&self, key: &str) -> PathBuf {
        let ext = if cfg!(target_os = "windows") { "dll" }
                  else if cfg!(target_os = "macos") { "dylib" }
                  else { "so" };
        self.cache_dir.join(format!("{}.{}", key, ext))
    }
    
    /// Try to load a cached .dll, returning the loaded function if successful
    fn load_cached_dll(&self, key: &str) -> Option<Box<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        let dll_path = self.cached_dll_path(key);
        if !dll_path.exists() {
            return None;
        }
        eprintln!("JIT: loading cached .dll '{}'", key);
        self.load_function(&dll_path, "compiled_routine")
    }
    
    /// Track a call to a routine and trigger compilation if hot.
    /// Returns true if a compiled version is available and should be used.
    pub fn track_call(&self, name: &str, source: &str) -> bool {
        // Check if already compiled
        if self.get_compiled_fn(name).is_some() {
            return true;
        }
        
        // Increment call count
        let mut counts = self.call_counts.lock().unwrap();
        let count = counts.get(name).copied().unwrap_or(0) + 1;
        counts.insert(name.to_string(), count);
        
        if count >= self.hot_threshold {
            eprintln!("JIT: hot routine '{}' ({} calls), compiling...", name, count);
            drop(counts); // release lock before compile
            
            if let Some(compiled_fn) = self.try_compile_routine(name, source) {
                eprintln!("JIT: compiled '{}' successfully!", name);
                return true;
            }
            eprintln!("JIT: compile '{}' failed, will keep interpreting", name);
        }
        
        false
    }
    
    /// Check if a routine has been compiled and cached (memory or disk)
    pub fn is_compiled(&self, name: &str, _source: &str) -> bool {
        // Check memory cache
        {
            let cache = self.fn_cache.lock().unwrap();
            if cache.contains_key(name) {
                return true;
            }
        }
        false
    }
    
    /// Set the hot threshold (minimum calls before compilation)
    pub fn set_hot_threshold(&mut self, n: u32) {
        self.hot_threshold = n;
    }
    
    /// Get a compiled function by routine name
    pub fn get_compiled_fn(&self, name: &str) -> Option<Arc<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        self.fn_cache.lock().unwrap().get(name).cloned()
    }
    
    /// Store a compiled function in the cache
    pub fn store_compiled_fn(&self, name: &str, func: Arc<dyn Fn() -> Result<i64, String> + Send + Sync>) {
        self.fn_cache.lock().unwrap().insert(name.to_string(), func);
    }

    /// Try to compile a program, store in fn_cache, and return an Arc'd function.
    pub fn try_compile(&self, program: &Program, name: &str) -> Option<Arc<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        let cache_key_str = Self::cache_key(name, &program.source);
        
        // Check memory cache first
        if let Some(f) = self.get_compiled_fn(name) {
            self.stats.lock().unwrap().cache_hits += 1;
            return Some(f);
        }
        
        // Check disk cache
        let dll_path = self.cached_dll_path(&cache_key_str);
        if dll_path.exists() {
            eprintln!("JIT: cache HIT for '{}' (loading .dll)", name);
            if let Some(f) = self.load_function(&dll_path, "compiled_routine") {
                let arc_fn = Arc::new(f);
                self.store_compiled_fn(name, arc_fn.clone());
                self.stats.lock().unwrap().cache_hits += 1;
                return Some(arc_fn);
            }
        }
        
        eprintln!("JIT: compiling '{}' (cache miss, cargo build ~12s)", name);
        
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
                        let arc_fn = Arc::new(f);
                        self.stats.lock().unwrap().successful_compilations += 1;
                        self.store_compiled_fn(name, arc_fn.clone());
                        // Save to persistent cache
                        let cache_path = self.cached_dll_path(&cache_key_str);
                        let _ = fs::copy(&dll_path, &cache_path);
                        eprintln!("JIT: cached .dll for '{}' at {:?}", name, cache_path);
                        Some(arc_fn)
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
    #[cfg(feature = "dll")]
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

    /// Stub sin feature "dll": la carga JIT de rutinas no está disponible.
    #[cfg(not(feature = "dll"))]
    fn load_function(&self, _dll_path: &Path, _fn_name: &str) -> Option<Box<dyn Fn() -> Result<i64, String> + Send + Sync>> {
        None
    }

    /// Try to compile by routine name and source
    pub fn try_compile_routine(&self, name: &str, source: &str) -> Option<Arc<dyn Fn() -> Result<i64, String> + Send + Sync>> {
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
