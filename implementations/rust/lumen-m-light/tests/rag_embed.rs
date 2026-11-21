//! Prueba de $DEVICE("rag:embed") — busqueda vectorial por coseno.
//!
//! No prueba que el modelo de embeddings sea bueno (eso se mide fuera, con
//! datos reales). Prueba que el DEVICE del motor hace lo que dice: producto
//! escalar sobre vectores precalculados, filtro por prefijo de id, y stats.

use lumen_mlight::{Compiler, Execution, GlobalEntry, MemoryHost, Subscript, Value, Vm};

fn g(ns: &str, subs: &[&str], valor: &str) -> GlobalEntry {
    GlobalEntry {
        ns: ns.to_string(),
        subs: subs.iter().map(|s| Subscript::String(s.to_string())).collect(),
        value: Value::String(valor.to_string()),
    }
}

fn host_con_corpus() -> MemoryHost {
    MemoryHost::from_entries(vec![
        g("RAG", &["doc", "mesa-001", "texto"], "Se acepta el DNI caducado si acredita identidad."),
        g("RAG", &["doc", "mesa-001", "vec"], "0.6,0.8"),
        g("RAG", &["doc", "mesa-002", "texto"], "La paella se hace con arroz y azafran."),
        g("RAG", &["doc", "mesa-002", "vec"], "0.0,1.0"),
        g("RAG", &["qvec", "abc123"], "1.0,0.0"),
    ])
}

fn correr(source: &str, host: &mut MemoryHost) -> String {
    let program = Compiler::compile(source).expect("no compila");
    let mut vm = Vm::new(program, host);
    vm.state.gas_limit = 200_000;
    let r = vm.run();
    assert!(matches!(r, Execution::Completed), "ejecucion fallida: {r:?}");
    vm.state.output.clone()
}

#[test]
fn embed_devuelve_el_trozo_mas_parecido() {
    let mut h = host_con_corpus();
    let out = correr(r#"W $DEVICE("rag:embed","abc123","RAG",2)"#, &mut h);
    assert!(out.contains("mesa-001"), "deberia ganar mesa-001 (cos 0.6): {out}");
    assert!(out.contains("0.60") || out.contains("0.600"), "score inesperado: {out}");
}

#[test]
fn embed_respeta_el_filtro_de_corpus() {
    let mut h = host_con_corpus();
    let out = correr(r#"W $DEVICE("rag:embed","abc123","RAG",5,"zzz-")"#, &mut h);
    assert_eq!(out.trim(), "", "el filtro zzz- no debe casar con nada");
}

#[test]
fn embed_filtro_por_prefijo_deja_pasar_lo_bueno() {
    let mut h = host_con_corpus();
    let out = correr(r#"W $DEVICE("rag:embed","abc123","RAG",5,"mesa-0")"#, &mut h);
    assert!(out.contains("mesa-001"), "el prefijo mesa-0 debe casar: {out}");
}

#[test]
fn embed_stats_cuenta_vectores_y_dimension() {
    let mut h = host_con_corpus();
    let out = correr(r#"W $DEVICE("rag:embed:stats","RAG")"#, &mut h);
    assert!(out.contains("vecs=2"), "esperaba vecs=2: {out}");
    assert!(out.contains("dim=2"), "esperaba dim=2: {out}");
}

#[test]
fn embed_sin_vector_de_pregunta_no_revienta() {
    let mut h = host_con_corpus();
    let out = correr(r#"W $DEVICE("rag:embed","no-existe","RAG",3)"#, &mut h);
    assert_eq!(out.trim(), "", "sin vector de pregunta debe devolver vacio");
}
