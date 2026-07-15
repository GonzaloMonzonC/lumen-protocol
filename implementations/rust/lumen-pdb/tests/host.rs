//! RedbHost: la VM M-Light corriendo standalone sobre redb, sin Python.

use lumen_mlight::{Compiler, Execution, Host, Subscript, Value, Vm};
use lumen_pdb::RedbHost;

fn temp_db(name: &str) -> String {
    let path = std::env::temp_dir().join(format!(
        "lumen-redbhost-{name}-{}.redb",
        std::process::id()
    ));
    let _ = std::fs::remove_file(&path);
    path.to_string_lossy().into_owned()
}

fn run(host: &mut RedbHost, source: &str) -> (Execution, lumen_mlight::VmState) {
    let program = Compiler::compile(source).unwrap();
    let mut vm = Vm::new(program, host);
    vm.state.gas_limit = 10_000;
    let execution = vm.run();
    (execution, vm.state)
}

#[test]
fn vm_runs_globals_order_data_and_kill_on_redb() {
    let path = temp_db("core");
    let mut host = RedbHost::open(&path).unwrap();
    let (execution, state) = run(
        &mut host,
        r#"S ^T(2)="two",^T(10)="ten",^T("a")="letter"
S first=$O(^T("")),second=$O(^T(first)),third=$O(^T(second))
S data=$D(^T(2)),miss=$D(^T(99))
K ^T(10)
S after=$O(^T(first))"#,
    );
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["first"], Value::Number(2.0));
    assert_eq!(state.vars["second"], Value::Number(10.0));
    assert_eq!(state.vars["third"], Value::String("a".into()));
    assert_eq!(state.vars["data"], Value::Number(1.0));
    assert_eq!(state.vars["miss"], Value::Number(0.0));
    assert_eq!(state.vars["after"], Value::String("a".into()));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn values_persist_across_reopen() {
    let path = temp_db("persist");
    {
        let mut host = RedbHost::open(&path).unwrap();
        let (execution, _) = run(&mut host, r#"S ^KEEP("k")="valor con ñ",^KEEP(1)=3.5"#);
        assert_eq!(execution, Execution::Completed);
        host.flush().unwrap();
    }
    let host = RedbHost::open(&path).unwrap();
    let text = host
        .get("KEEP", &[Subscript::String("k".into())])
        .unwrap()
        .unwrap();
    let number = host.get("KEEP", &[Subscript::Number(1.0)]).unwrap().unwrap();
    assert_eq!(text, Value::String("valor con ñ".into()));
    assert_eq!(number, Value::Number(3.5));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn transactions_nest_commit_and_rollback() {
    let path = temp_db("txn");
    let mut host = RedbHost::open(&path).unwrap();
    let (execution, state) = run(
        &mut host,
        r#"S ^TX("base")=1
TSTART
S ^TX("outer")=1
TSTART
S ^TX("inner")=1,^TX("base")=2
S mid=$G(^TX("inner"))
TROLLBACK
S gone=$D(^TX("inner")),base=$G(^TX("base"))
TCOMMIT
S outer=$G(^TX("outer"))"#,
    );
    assert_eq!(execution, Execution::Completed);
    // Dentro de la transacción se leen las propias escrituras…
    assert_eq!(state.vars["mid"], Value::Number(1.0));
    // …el rollback anidado deshace solo el nivel interno…
    assert_eq!(state.vars["gone"], Value::Number(0.0));
    assert_eq!(state.vars["base"], Value::Number(1.0));
    // …y el commit externo persiste lo suyo.
    assert_eq!(state.vars["outer"], Value::Number(1.0));
    assert_eq!(host.transaction_level(), 0);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn error_inside_transaction_rolls_back_everything() {
    let path = temp_db("abort");
    let mut host = RedbHost::open(&path).unwrap();
    let program = Compiler::compile("TSTART\nS ^AB(1)=1\nS ^AB(2)=2\nTCOMMIT").unwrap();
    let mut vm = Vm::new(program, &mut host);
    vm.state.gas_budget = 2; // GAS_EXHAUSTED a mitad de transacción
    assert_eq!(vm.run_slice(10), Execution::Error);
    assert_eq!(host.transaction_level(), 0);
    assert_eq!(host.data("AB", &[Subscript::Number(1.0)]).unwrap(), 0);
    let _ = std::fs::remove_file(&path);
}

#[test]
fn kill_inside_nested_transaction_restores_subtree_on_rollback() {
    let path = temp_db("killtx");
    let mut host = RedbHost::open(&path).unwrap();
    let (execution, state) = run(
        &mut host,
        r#"S ^K(1)="a",^K(1,1)="b",^K(2)="c"
TSTART
TSTART
K ^K(1)
S during=$D(^K(1))
TROLLBACK
S restored=$D(^K(1)),child=$G(^K(1,1))
TCOMMIT"#,
    );
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["during"], Value::Number(0.0));
    assert_eq!(state.vars["restored"], Value::Number(11.0));
    assert_eq!(state.vars["child"], Value::String("b".into()));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn routines_load_from_routine_global() {
    let path = temp_db("routine");
    let mut host = RedbHost::open(&path).unwrap();
    host.set(
        "ROUTINE",
        &[Subscript::String("SUMA".into()), Subscript::Number(1.0)],
        Value::String("S result=$1+$2".into()),
    )
    .unwrap();
    host.set(
        "ROUTINE",
        &[Subscript::String("SUMA".into()), Subscript::Number(2.0)],
        Value::String("Q".into()),
    )
    .unwrap();
    let (execution, state) = run(&mut host, "D ^SUMA(20,22) H");
    assert_eq!(execution, Execution::Halted);
    assert_eq!(state.vars["result"], Value::Number(42.0));
    let _ = std::fs::remove_file(&path);
}

#[test]
fn lock_unlock_and_new_functions_work_end_to_end() {
    let path = temp_db("lock");
    let mut host = RedbHost::open(&path).unwrap();
    let (execution, state) = run(
        &mut host,
        r#"L ^MUTEX("job")
S ^SAFE("v")=$C(76,85)_$FN(1234.5,",",0)
UNLOCK ^MUTEX("job")
S out=$G(^SAFE("v")),code=$A(out)"#,
    );
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["out"], Value::String("LU1,235".into()));
    assert_eq!(state.vars["code"], Value::Number(76.0));
    let _ = std::fs::remove_file(&path);
}
