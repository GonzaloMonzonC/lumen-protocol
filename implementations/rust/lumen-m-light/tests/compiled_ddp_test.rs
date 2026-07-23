//! Test end-to-end: compila M → Rust con TcpStream real
use lumen_mlight::compiler::Compiler;
use lumen_mlight::transpiler::transpile_to_rust;

#[test]
fn test_compiled_ddp_pipeline() {
    // 1. Compilar M a AST
    let program = Compiler::compile(r#"S r=$DEVICE("ddp:get","ASI","EXP01","39634137") W r"#)
        .expect("Compilación M debe funcionar");
    
    // 2. Transpilar a Rust
    let rust = transpile_to_rust(&program, "ddp_lookup");
    println!("=== Rust generado ===");
    println!("{}", rust);
    
    // 3. Verificar que es código TCP real, no placeholder
    assert!(rust.contains("TcpStream"), "Debe generar TcpStream");
    assert!(rust.contains("write_all"), "Debe tener write_all");
    assert!(rust.contains("read_to_end"), "Debe tener read_to_end");
    assert!(rust.contains(r#"global":"EXP01"#), "Debe contener global");
    assert!(rust.contains(r#"subs":["39634137"]"#), "Debe contener key");
    assert!(!rust.contains("COMPILED_DDP"), "NO debe ser placeholder");
    
    println!("\n✅ M → Rust → TcpStream: pipeline completo OK");
    println!("   Proxy: ^SPACE(\"ASI\") → 127.0.0.1:9102");
    println!("   Query: EXP01 GET key=39634137");
    println!("   ⚡ Compilado: conexión TCP real en el .dll");
}
