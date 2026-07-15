use lumen_mlight::{Compiler, Execution, GlobalEntry, Host, MemoryHost, Subscript, Value, Vm};
use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Deserialize)]
struct GoldenCase {
    name: String,
    source: String,
    #[serde(default)]
    globals: Vec<GlobalEntry>,
    #[serde(default)]
    expected_vars: BTreeMap<String, Value>,
    #[serde(default)]
    expected_globals: Vec<GlobalEntry>,
    #[serde(default)]
    output: String,
    execution: Execution,
}

fn run(source: &str) -> (Execution, lumen_mlight::VmState, Vec<GlobalEntry>) {
    let program = Compiler::compile(source).unwrap();
    let mut host = MemoryHost::default();
    let (execution, state) = {
        let mut vm = Vm::new(program, &mut host);
        vm.state.gas_limit = 10_000;
        let execution = vm.run();
        (execution, vm.state)
    };
    (execution, state, host.entries())
}

#[test]
fn arithmetic_is_strictly_left_to_right() {
    let (execution, state, _) = run("S x=2+3*4,y=17\\5,z=17#5,n=\"12.5\",cast=+n,neg=-n");
    assert_eq!(execution, Execution::Completed);
    assert_eq!(state.vars["x"], Value::Number(20.0));
    assert_eq!(state.vars["y"], Value::Number(3.0));
    assert_eq!(state.vars["z"], Value::Number(2.0));
    assert_eq!(state.vars["cast"], Value::Number(12.5));
    assert_eq!(state.vars["neg"], Value::Number(-12.5));
}

#[test]
fn globals_data_order_and_kill_share_m_semantics() {
    let (_, state, globals) = run(r#"S ^T(2)="two",^T(10)="ten",^T("a")="letter"
S first=$O(^T("")),second=$O(^T(first)),data=$D(^T(2))
K ^T(10)"#);
    assert_eq!(state.vars["first"], Value::Number(2.0));
    assert_eq!(state.vars["second"], Value::Number(10.0));
    assert_eq!(state.vars["data"], Value::Number(1.0));
    assert_eq!(globals.len(), 2);
}

#[test]
fn indirection_reads_and_writes_locals_and_globals() {
    let (_, state, globals) = run(r#"S target="local",@(target)=42
S gref="^DYNAMIC(""clave"")",@gref="valor",copy=@gref"#);
    assert_eq!(state.vars["local"], Value::Number(42.0));
    assert_eq!(state.vars["copy"], Value::String("valor".to_string()));
    assert_eq!(globals[0].ns, "DYNAMIC");
    assert_eq!(
        globals[0].subs,
        vec![Subscript::String("clave".to_string())]
    );
}

#[test]
fn transactions_commit_and_rollback_atomically() {
    let (_, _, globals) = run(r#"TSTART S ^TX("committed")=1 TCOMMIT
TSTART S ^TX("rolled_back")=2 TROLLBACK"#);
    assert_eq!(globals.len(), 1);
    assert_eq!(globals[0].subs[0], Subscript::String("committed".into()));
}

#[test]
fn if_else_and_range_for_execute_blocks() {
    let (_, state, _) = run(r#"S total=0
F i=1:1:4 { S total=total+i }
I total=10 { S result="ok" } ELSE { S result="bad" }"#);
    assert_eq!(state.vars["total"], Value::Number(10.0));
    assert_eq!(state.vars["result"], Value::String("ok".to_string()));
}

#[test]
fn gas_state_round_trips_and_resumes_exactly() {
    let program = Compiler::compile("S a=1\nS b=2\nS c=3").unwrap();
    let mut first_host = MemoryHost::default();
    let state = {
        let mut vm = Vm::new(program.clone(), &mut first_host);
        assert_eq!(vm.run_slice(1), Execution::Yielded);
        assert_eq!(vm.state.ip, 1);
        serde_json::from_str(&serde_json::to_string(&vm.state).unwrap()).unwrap()
    };
    let mut resumed_host = MemoryHost::default();
    let mut resumed = Vm::resume(program, state, &mut resumed_host).unwrap();
    assert_eq!(resumed.run_slice(10), Execution::Completed);
    assert_eq!(resumed.state.vars["c"], Value::Number(3.0));
    assert_eq!(resumed.state.gas_used, 3);
}

#[test]
fn shared_json_golden_vectors_are_stable() {
    let cases: Vec<GoldenCase> = serde_json::from_str(include_str!("golden_cases.json")).unwrap();
    assert_eq!(cases.len(), 8);
    for case in cases {
        let program = Compiler::compile(&case.source).unwrap();
        let mut host = MemoryHost::from_entries(case.globals);
        let (execution, state) = {
            let mut vm = Vm::new(program, &mut host);
            vm.state.gas_limit = 10_000;
            let execution = vm.run();
            (execution, vm.state)
        };
        assert_eq!(execution, case.execution, "{} execution", case.name);
        for (name, expected) in case.expected_vars {
            assert_eq!(
                state.vars.get(&name),
                Some(&expected),
                "{} var {name}",
                case.name
            );
        }
        assert_eq!(state.output, case.output, "{} output", case.name);
        if !case.expected_globals.is_empty() {
            assert_eq!(
                host.entries(),
                case.expected_globals,
                "{} globals",
                case.name
            );
        }
    }
}

#[test]
fn for_loop_yields_and_resumes_inside_the_loop() {
    let program = Compiler::compile("S total=0\nF i=1:1:10 { S total=total+i }").unwrap();
    let mut host = MemoryHost::default();
    let mut state = {
        let mut vm = Vm::new(program.clone(), &mut host);
        assert_eq!(vm.run_slice(3), Execution::Yielded);
        assert!(!vm.state.loop_frames.is_empty());
        vm.state
    };
    let mut yields = 1;
    loop {
        state = serde_json::from_str(&serde_json::to_string(&state).unwrap()).unwrap();
        let mut vm = Vm::resume(program.clone(), state, &mut host).unwrap();
        match vm.run_slice(3) {
            Execution::Yielded => {
                yields += 1;
                state = vm.state;
            }
            Execution::Completed => {
                assert_eq!(vm.state.vars["total"], Value::Number(55.0));
                assert!(vm.state.loop_frames.is_empty());
                break;
            }
            other => panic!("unexpected execution: {other:?}"),
        }
    }
    assert!(yields >= 3);
}

#[test]
fn transactions_are_non_yielding_and_errors_roll_back() {
    let program =
        Compiler::compile("TSTART\nS ^ATOMIC(1)=1\nS ^ATOMIC(2)=2\nTCOMMIT\nS after=1").unwrap();
    let mut host = MemoryHost::default();
    let state = {
        let mut vm = Vm::new(program, &mut host);
        assert_eq!(vm.run_slice(1), Execution::Yielded);
        vm.state
    };
    assert_eq!(state.ip, 4);
    assert_eq!(host.entries().len(), 2);

    let bad = Compiler::compile("TSTART\nS ^ATOMIC(3)=3\nTCOMMIT").unwrap();
    let before = host.entries();
    let mut vm = Vm::new(bad, &mut host);
    vm.state.gas_budget = 1;
    assert_eq!(vm.run_slice(10), Execution::Error);
    assert_eq!(vm.host.entries(), before);
    assert_eq!(vm.host.transaction_level(), 0);
}

#[test]
fn do_goto_and_new_follow_serializable_control_state() {
    let source = r#"S x=1
D SUB
G END
SUB
N x
S x=2
Q
END
W x
H"#;
    let (execution, state, _) = run(source);
    assert_eq!(execution, Execution::Halted);
    assert_eq!(state.vars["x"], Value::Number(1.0));
    assert_eq!(state.output, "1");
    assert!(state.call_stack.is_empty());
    assert!(state.local_scopes.is_empty());
}

#[test]
fn postconditional_quit_propagates_to_the_for_loop() {
    let (_, state, _) = run("S total=0\nF i=1:1:100 { Q:i=4 S total=total+1 }");
    assert_eq!(state.vars["i"], Value::Number(4.0));
    assert_eq!(state.vars["total"], Value::Number(3.0));
}

#[test]
fn do_binds_and_restores_positional_arguments() {
    let source = "D ADD(2,3)\nH\nADD\nS result=$1+$2\nQ";
    let (execution, state, _) = run(source);
    assert_eq!(execution, Execution::Halted);
    assert_eq!(state.vars["result"], Value::Number(5.0));
    assert!(!state.vars.contains_key("$1"));
    assert!(!state.vars.contains_key("$2"));
    assert!(state.argument_scopes.is_empty());
}

#[test]
fn external_routine_receives_arguments_without_leaking_scope() {
    let program = Compiler::compile("S x=1 D ^ADD(4,5) H").unwrap();
    let mut host = MemoryHost::default();
    host.add_routine("ADD", "N x S x=$1+$2,result=x Q");
    let mut vm = Vm::new(program, &mut host);
    assert_eq!(vm.run_slice(100), Execution::Halted);
    assert_eq!(vm.state.vars["x"], Value::Number(1.0));
    assert_eq!(vm.state.vars["result"], Value::Number(9.0));
    assert!(!vm.state.vars.contains_key("$1"));
    assert!(vm.state.local_scopes.is_empty());
}

#[test]
fn read_prompt_assigns_host_input_to_the_target() {
    let program = Compiler::compile("R \"name\":who W who").unwrap();
    let mut host = MemoryHost::default();
    host.push_input("Ada");
    let mut vm = Vm::new(program, &mut host);
    assert_eq!(vm.run_slice(100), Execution::Completed);
    assert_eq!(vm.state.vars["who"], Value::String("Ada".into()));
    assert_eq!(vm.state.output, "Ada");
}
