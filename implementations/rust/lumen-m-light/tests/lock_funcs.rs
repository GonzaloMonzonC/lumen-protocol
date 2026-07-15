//! Fase 5.1: LOCK/UNLOCK + funciones $A/$C/$FN y variables $H/$T.

use lumen_mlight::{Compiler, Execution, Host, MemoryHost, Subscript, Value, Vm};

fn run(source: &str) -> (Execution, lumen_mlight::VmState, MemoryHost) {
    let program = Compiler::compile(source).unwrap();
    let mut host = MemoryHost::default();
    let (execution, state) = {
        let mut vm = Vm::new(program, &mut host);
        vm.state.gas_limit = 10_000;
        let execution = vm.run();
        (execution, vm.state)
    };
    (execution, state, host)
}

#[test]
fn ascii_and_char_match_python_reference() {
    let (execution, state, _) = run(
        r#"S code=$A("LUMEN"),second=$A("LUMEN",2),out=$A("LUMEN",99),empty=$A("")
S txt=$C(76,85,77),accent=$C(233),bad=$C(-1)"#,
    );
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["code"], Value::Number(76.0));
    assert_eq!(state.vars["second"], Value::Number(85.0));
    assert_eq!(state.vars["out"], Value::Number(-1.0));
    assert_eq!(state.vars["empty"], Value::Number(-1.0));
    assert_eq!(state.vars["txt"], Value::String("LUM".into()));
    assert_eq!(state.vars["accent"], Value::String("é".into()));
    assert_eq!(state.vars["bad"], Value::String("?".into()));
}

#[test]
fn char_ascii_round_trip() {
    let (_, state, _) = run(r#"S rt=$A($C(8364))"#);
    assert_eq!(state.vars["rt"], Value::Number(8364.0));
}

#[test]
fn fnumber_formats_commas_signs_and_decimals() {
    let (execution, state, _) = run(
        r#"S plain=$FN(1234567.891,"",2),comma=$FN(1234567.891,",",2)
S plus=$FN(42,"+"),minus=$FN(-42,"-"),paren=$FN(-1234.5,"P,",0)
S trail=$FN(-7,"T"),zero=$FN(-0.4,"",0)"#,
    );
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["plain"], Value::String("1234567.89".into()));
    assert_eq!(state.vars["comma"], Value::String("1,234,567.89".into()));
    assert_eq!(state.vars["plus"], Value::String("+42".into()));
    assert_eq!(state.vars["minus"], Value::String("42".into()));
    assert_eq!(state.vars["paren"], Value::String("(1,235)".into()));
    assert_eq!(state.vars["trail"], Value::String("7-".into()));
    assert_eq!(state.vars["zero"], Value::String("0".into()));
}

#[test]
fn horolog_has_m_shape_and_utc_base() {
    let (execution, state, _) = run(r#"S h=$H,days=$P(h,",",1),secs=$P(h,",",2)"#);
    assert_eq!(execution, Execution::Completed);
    let days = state.vars["days"].as_number();
    let secs = state.vars["secs"].as_number();
    // 2026 ≈ día 67 mil y pico; cualquier valor plausible posterior a 2026-01-01.
    assert!(days > 67_500.0, "days={days}");
    assert!((0.0..86_400.0).contains(&secs), "secs={secs}");
}

#[test]
fn lock_and_unlock_track_reentrant_counters() {
    let (execution, _, host) = run(
        r#"L ^T("a")
L ^T("a")
L ^T("b")
UNLOCK ^T("a")
UNLOCK ^T("a"),^T("b")"#,
    );
    assert_eq!(execution, Execution::Completed);
    assert_eq!(host.held_locks(), 0);
}

#[test]
fn bare_lock_and_unlock_release_everything() {
    let (execution, _, host) = run("L ^A\nL ^B(1)\nL");
    assert_eq!(execution, Execution::Completed);
    assert_eq!(host.held_locks(), 0);
    let (execution, _, host) = run("L ^A\nL ^B(1)\nUNLOCK");
    assert_eq!(execution, Execution::Completed);
    assert_eq!(host.held_locks(), 0);
}

#[test]
fn timed_lock_sets_test_variable() {
    let (execution, state, _) = run(r#"L ^T("x"):0 S got=$T I $TEST S ok=1"#);
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["got"], Value::Number(1.0));
    assert_eq!(state.vars["ok"], Value::Number(1.0));
}

/// Host que niega la primera adquisición para simular contención.
#[derive(Default)]
struct ContentiousHost {
    inner: MemoryHost,
    denials: usize,
    pub attempts: usize,
}

impl Host for ContentiousHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        self.inner.get(ns, subs)
    }
    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        self.inner.set(ns, subs, value)
    }
    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        self.inner.kill(ns, subs)
    }
    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        self.inner.data(ns, subs)
    }
    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        self.inner.order(ns, parent, current, direction)
    }
    fn transaction_start(&mut self) -> Result<(), String> {
        self.inner.transaction_start()
    }
    fn transaction_commit(&mut self) -> Result<(), String> {
        self.inner.transaction_commit()
    }
    fn transaction_rollback(&mut self) -> Result<(), String> {
        self.inner.transaction_rollback()
    }
    fn transaction_level(&self) -> usize {
        self.inner.transaction_level()
    }
    fn lock(
        &mut self,
        ns: &str,
        subs: &[Subscript],
        timeout: Option<f64>,
    ) -> Result<bool, String> {
        self.attempts += 1;
        if self.denials > 0 {
            self.denials -= 1;
            return Ok(false);
        }
        self.inner.lock(ns, subs, timeout)
    }
    fn unlock(&mut self, ns: &str, subs: &[Subscript]) -> Result<(), String> {
        self.inner.unlock(ns, subs)
    }
    fn unlock_all(&mut self) -> Result<(), String> {
        self.inner.unlock_all()
    }
}

#[test]
fn blocking_lock_yields_and_retries_the_same_instruction() {
    let program = Compiler::compile("S before=1\nL ^MUTEX\nS after=1").unwrap();
    let mut host = ContentiousHost {
        denials: 2,
        ..Default::default()
    };
    let mut vm = Vm::new(program.clone(), &mut host);
    vm.state.gas_limit = 100;
    // Dos denegaciones → dos yields sobre la MISMA instrucción.
    assert_eq!(vm.run_slice(100), Execution::Yielded);
    assert_eq!(vm.state.ip, 1);
    assert!(!vm.state.vars.contains_key("after"));
    assert_eq!(vm.run_slice(100), Execution::Yielded);
    assert_eq!(vm.state.ip, 1);
    let state = vm.state;
    let mut resumed = Vm::resume(program, state, &mut host).unwrap();
    assert_eq!(resumed.run_slice(100), Execution::Completed);
    assert_eq!(resumed.state.vars["after"], Value::Number(1.0));
    assert_eq!(host.attempts, 3);
}

#[test]
fn external_routine_with_for_completes_despite_tiny_gas_slices() {
    // Regresión: el slice agotado dentro de D ^RUTINA reiniciaba la rutina
    // desde cero cada tick (livelock). Las rutinas ejecutan atómicas.
    let program = Compiler::compile("D ^SUMLOOP\nS after=1").unwrap();
    let mut host = MemoryHost::default();
    host.add_routine("SUMLOOP", "S t=0\nF i=1:1:30 { S t=t+i }\nQ");
    let mut vm = Vm::new(program, &mut host);
    vm.state.gas_limit = 2;
    let mut slices = 0;
    loop {
        match vm.run_slice(2) {
            Execution::Yielded => {
                slices += 1;
                assert!(slices < 50, "livelock: la rutina nunca termina");
            }
            Execution::Completed => break,
            other => panic!("unexpected execution: {other:?}"),
        }
    }
    assert_eq!(vm.state.vars["t"], Value::Number(465.0));
    assert_eq!(vm.state.vars["after"], Value::Number(1.0));
}

#[test]
fn blocked_lock_inside_for_body_resumes_without_skipping() {
    let program = Compiler::compile("S n=0\nF i=1:1:2 { L ^LOOP S n=n+1 UNLOCK ^LOOP }").unwrap();
    let mut host = ContentiousHost {
        denials: 1,
        ..Default::default()
    };
    let mut vm = Vm::new(program.clone(), &mut host);
    vm.state.gas_limit = 1_000;
    assert_eq!(vm.run_slice(1_000), Execution::Yielded);
    let state = vm.state;
    let mut resumed = Vm::resume(program, state, &mut host).unwrap();
    assert_eq!(resumed.run_slice(1_000), Execution::Completed);
    // El cuerpo se ejecutó las 2 veces: el LOCK bloqueado no se saltó.
    assert_eq!(resumed.state.vars["n"], Value::Number(2.0));
    assert_eq!(host.inner.held_locks(), 0);
}
