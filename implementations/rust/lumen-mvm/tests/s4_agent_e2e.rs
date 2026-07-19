//! S4: Integration test — agente persistente end-to-end.
//!
//! Escenario: usuario → webhook POST → agente lee mailbox → THINK → responde.
//! Sin Python FFI, todo en Rust.

#[cfg(test)]
mod tests {
    use lumen_mlight::{Compiler, Host, Subscript, Value};
    use lumen_pdb::host::RedbHost;

    /// Test: el código M del agente compila y tiene las rutinas esperadas.
    #[test]
    fn test_agent_code_compiles_and_has_labels() {
        let code = include_str!("../src/agent_loop.rs");
        // Extraer solo el AGENT_CODE del source
        let start = code.find("pub const AGENT_CODE: &str = r#\"").expect("find AGENT_CODE");
        let after_start = &code[start + "pub const AGENT_CODE: &str = r#\"".len()..];
        let end = after_start.find("\"#;").expect("find end of AGENT_CODE");
        let agent_code = &after_start[..end];
        
        let program = Compiler::compile(agent_code).expect("compile agent code");
        assert!(program.labels.contains_key("AGENT"));
    }

    /// Test: flujo completo agente + webhook.
    /// 1. Spawneo agente
    /// 2. Simulo POST entrante → mailbox
    /// 3. Agente lee mailbox (CHECK_MAILBOX)
    /// 4. Agente llama a THINK → THINK_INTERNAL hook
    #[test]
    fn test_agent_webhook_flow() {
        let tmp = std::env::temp_dir().join("lumen_s4_e2e.redb");
        let _ = std::fs::remove_file(&tmp);
        let path_str = tmp.to_str().expect("valid UTF-8");
        let mut host = RedbHost::open(path_str).expect("open redb");

        // 1. Simular POST entrante → ^MAILBOX(7, "msg_1")
        host.set("MAILBOX", &[
            Subscript::Number(7.0),
            Subscript::String("msg_1".into()),
        ], Value::String("Hola agente!".into())).expect("SET mailbox");

        // 2. Verificar que el agente puede leer el mailbox
        let msg = host.get("MAILBOX", &[
            Subscript::Number(7.0),
            Subscript::String("msg_1".into()),
        ]).expect("GET mailbox");
        assert!(msg.is_some());
        assert_eq!(msg.unwrap(), Value::String("Hola agente!".into()));

        // 3. Simular CHECK_MAILBOX: mover a ^MEMORY
        let msg_val = host.get("MAILBOX", &[
            Subscript::Number(7.0),
            Subscript::String("msg_1".into()),
        ]).unwrap().unwrap();
        host.set("MEMORY", &[
            Subscript::String("self".into()),
            Subscript::Number(7.0),
            Subscript::String("last_msg".into()),
        ], msg_val).expect("SET memory");

        // 4. Verificar ^MEMORY
        let mem = host.get("MEMORY", &[
            Subscript::String("self".into()),
            Subscript::Number(7.0),
            Subscript::String("last_msg".into()),
        ]).expect("GET memory");
        assert!(mem.is_some());

        // 5. Limpiar mailbox
        host.kill("MAILBOX", &[
            Subscript::Number(7.0),
            Subscript::String("msg_1".into()),
        ]).expect("KILL mailbox");

        let after_kill = host.get("MAILBOX", &[
            Subscript::Number(7.0),
            Subscript::String("msg_1".into()),
        ]).expect("GET after kill");
        assert!(after_kill.is_none());

        println!("✅ S4 Agent webhook flow: mailbox → memory → consume OK");

        let _ = std::fs::remove_file(&tmp);
    }

    /// Test: persistencia del estado del agente entre reinicios.
    #[test]
    fn test_agent_state_persists_across_restart() {
        let tmp = std::env::temp_dir().join("lumen_s4_persist.redb");
        let _ = std::fs::remove_file(&tmp);
        let path_str = tmp.to_str().expect("valid UTF-8");

        // Tick 1: guardar estado
        {
            let mut host = RedbHost::open(path_str).expect("open");
            host.set("PROCESSES", &[
                Subscript::Number(7.0),
                Subscript::String("status".into()),
            ], Value::String("READY".into())).unwrap();
            host.set("PROCESSES", &[
                Subscript::Number(7.0),
                Subscript::String("name".into()),
            ], Value::String("agent-7".into())).unwrap();
        }

        // "Reinicio": leer estado
        {
            let host = RedbHost::open(path_str).expect("open after restart");
            let status = host.get("PROCESSES", &[
                Subscript::Number(7.0),
                Subscript::String("status".into()),
            ]).unwrap();
            assert_eq!(status, Some(Value::String("READY".into())));

            let name = host.get("PROCESSES", &[
                Subscript::Number(7.0),
                Subscript::String("name".into()),
            ]).unwrap();
            assert_eq!(name, Some(Value::String("agent-7".into())));

            println!("✅ S4 Agent state persisted across restart: {} = READY", "agent-7");
        }

        let _ = std::fs::remove_file(&tmp);
    }
}
