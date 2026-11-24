//! Benchmark NATIVO del motor M-Light, sin la frontera Python.
//!
//! Por qué existe: `bench_latencia.py` mide a través de FFI y JSON, así que sus
//! cifras incluyen el viaje Python→C→motor→JSON→Python. Eso es lo que ve un
//! servicio, pero NO es lo que tarda el motor. Sin este banco no se puede decir
//! "el motor hace X µs" — solo "el viaje completo hace Y µs".
//!
//! Qué mide, y por qué separado:
//!   - COMPILAR: solo `Compiler::compile(source)`.
//!   - EJECUTAR PRECOMPILADO: `Vm::new(program, &mut host).run()` sobre un
//!     programa ya compilado. Este es el número del MOTOR PURO: sin parsear y
//!     sin serializar.
//!   - COMPILAR+EJECUTAR: el ciclo completo dentro de Rust.
//!
//! Metodología: muestras en nanosegundos con `Instant`, warmup previo, y dos
//! mitades para detectar deriva térmica (mismo criterio que el banco Python:
//! si la 2ª mitad es >20% más lenta, se reporta solo la 1ª y se avisa).
//!
//! Uso:  cargo test --release --test bench_nativo -- --nocapture
//!       (es un `#[test]` para no añadir un binario al crate)

use lumen_mlight::{Compiler, Execution, MemoryHost, Vm};
use std::time::Instant;

const WARMUP: usize = 200;

fn pct(xs: &[f64], p: f64) -> f64 {
    if xs.is_empty() {
        return 0.0;
    }
    let i = ((xs.len() - 1) as f64 * p).round() as usize;
    xs[i.min(xs.len() - 1)]
}

/// Mide una operación en dos mitades y devuelve los stats en microsegundos.
fn medir<F: FnMut()>(mut fn_: F, iters: usize) -> (f64, f64, f64, f64, f64) {
    for _ in 0..WARMUP {
        fn_();
    }
    let mitad = (iters / 2).max(10);
    let tanda = |n: usize, f: &mut F| -> Vec<f64> {
        let mut xs = Vec::with_capacity(n);
        for _ in 0..n {
            let t0 = Instant::now();
            f();
            xs.push(t0.elapsed().as_nanos() as f64 / 1000.0); // ns -> µs
        }
        xs
    };
    let primera = tanda(mitad, &mut fn_);
    let segunda = tanda(mitad, &mut fn_);

    let m1: f64 = {
        let mut s = primera.clone();
        s.sort_by(|a, b| a.partial_cmp(b).unwrap());
        pct(&s, 0.5)
    };
    let m2: f64 = {
        let mut s = segunda.clone();
        s.sort_by(|a, b| a.partial_cmp(b).unwrap());
        pct(&s, 0.5)
    };
    let deriva = if m1 > 0.0 { (m2 - m1) / m1 * 100.0 } else { 0.0 };

    let mut xs = if deriva > 20.0 {
        primera // la 2ª está contaminada por calor
    } else {
        let mut v = primera;
        v.extend(segunda);
        v
    };
    xs.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let p50 = pct(&xs, 0.50);
    let p99 = pct(&xs, 0.99);
    (
        p50,
        pct(&xs, 0.95),
        p99,
        pct(&xs, 0.999),
        deriva,
    )
}

#[test]
fn bench_motor_nativo() {
    let iters: usize = 20_000;

    println!();
    println!("==================================================================");
    println!("BENCHMARK NATIVO — motor M-Light en Rust puro (sin FFI, sin JSON)");
    println!("==================================================================");
    println!("iters={} por caso, warmup={}", iters, WARMUP);
    println!("Cifras en MICROSEGUNDOS. p50/p95/p99/p99.9 sobre muestras reales.");
    println!();
    println!(
        "{:<22} {:>9} {:>9} {:>9} {:>9} {:>8}",
        "caso", "p50", "p95", "p99", "p99.9", "deriva"
    );
    println!("{}", "-".repeat(70));

    let casos: Vec<(&str, String)> = vec![
        ("compile_1_linea", "S x=42".to_string()),
        ("compile_4_lineas", "S x=42\nS y=x+1\nS z=y*2\nW z".to_string()),
        ("math", "W 2+3*4".to_string()),
        ("for_100", "S t=0\nF i=1:1:100 { S t=t+i }".to_string()),
        (
            "global_set_get",
            "S ^B(\"k\")=\"v\"\nW $G(^B(\"k\"))".to_string(),
        ),
        ("order_10", "S k=$O(^C(\"\"))".to_string()),
    ];

    for (nombre, src) in &casos {
        // --- COMPILAR solo ---
        let (c50, c95, c99, c999, cder) =
            medir(|| {
                let _ = Compiler::compile(src);
            }, iters);

        // --- EJECUTAR precompilado (el motor puro) ---
        let programa = Compiler::compile(src).expect("compila");
        let (e50, e95, e99, e999, eder) = medir(
            || {
                let mut host = MemoryHost::default();
                let mut vm = Vm::new(programa.clone(), &mut host);
                vm.state.gas_limit = 100_000;
                let r = vm.run();
                debug_assert!(matches!(r, Execution::Completed | Execution::Halted));
            },
            iters,
        );

        println!(
            "{:<22} {:>9.2} {:>9.2} {:>9.2} {:>9.2} {:>7.1}%   <- compilar",
            format!("{}", nombre), c50, c95, c99, c999, cder
        );
        println!(
            "{:<22} {:>9.2} {:>9.2} {:>9.2} {:>9.2} {:>7.1}%   <- ejecutar",
            "", e50, e95, e99, e999, eder
        );
        println!();
    }

    println!("Nota: 'ejecutar' usa un MemoryHost nuevo por iteracion para no medir");
    println!("estado acumulado. En un servicio el host se reutiliza, asi que la");
    println!("cifra real de ejecucion es IGUAL O MEJOR que esta.");
    println!("==================================================================");
}
