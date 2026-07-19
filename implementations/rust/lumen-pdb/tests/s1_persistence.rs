//! Test de adopción S1: Test 1 — Persistencia de memoria.
//!
//! El requisito de Kimi: S ^X=1, matar proceso, reiniciar, $G(^X)=1.
//! Verifica que RedbHost persiste ^GLOBALS en disco (redb).

#[cfg(test)]
mod tests {
    use lumen_pdb::host::RedbHost;
    use lumen_mlight::{Host, Subscript, Value};

    fn open_host(path: &std::path::Path) -> RedbHost {
        RedbHost::open(path.to_str().expect("valid UTF-8 path")).expect("open redb")
    }

    /// Test 1 del contrato de adopción:
    /// S ^MEMORY("self",42,"belief","rust")="good"
    /// Matar → Reiniciar → $G(^MEMORY(...)) = "good"
    #[test]
    fn test_s1_persistence_across_restart() {
        let tmp = std::env::temp_dir().join("lumen_s1_test1.redb");
        let _ = std::fs::remove_file(&tmp);

        {
            let mut host = open_host(&tmp);
            let subs = vec![
                Subscript::String("self".into()),
                Subscript::Number(42.0),
                Subscript::String("belief".into()),
                Subscript::String("rust".into()),
            ];
            host.set("MEMORY", &subs, Value::String("good".into())).unwrap();
        }

        {
            let host = open_host(&tmp);
            let subs = vec![
                Subscript::String("self".into()),
                Subscript::Number(42.0),
                Subscript::String("belief".into()),
                Subscript::String("rust".into()),
            ];
            let val = host.get("MEMORY", &subs).unwrap();
            assert_eq!(val, Some(Value::String("good".into())));
            println!("✅ Test 1 PASS: $G = 'good' tras reinicio");
        }

        let _ = std::fs::remove_file(&tmp);
    }

    /// $DATA post-reinicio
    #[test]
    fn test_s1_data_after_restart() {
        let tmp = std::env::temp_dir().join("lumen_s1_test1_data.redb");
        let _ = std::fs::remove_file(&tmp);

        {
            let mut host = open_host(&tmp);
            host.set("X", &[Subscript::String("test".into())], Value::Number(42.0)).unwrap();
        }

        {
            let host = open_host(&tmp);
            let d = host.data("X", &[Subscript::String("test".into())]).unwrap();
            assert_eq!(d, 1);
            println!("✅ $DATA post-restart: {}", d);
        }

        let _ = std::fs::remove_file(&tmp);
    }
}
