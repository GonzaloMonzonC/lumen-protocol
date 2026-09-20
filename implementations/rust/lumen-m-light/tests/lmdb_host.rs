//! Tests de integración del backend LMDB de MemoryHost (feature "lmdb").
//!
//! Ejecutar: cargo test --features lmdb --test lmdb_host
//!
//! Cubre: roundtrip + persistencia real (reabrir env), $D (0/1/10/11),
//! KILL de subárbol (conteo), $O forward/backward (cursor), transacciones
//! anidables con rollback (undo-log), y equivalencia del orden RAM↔LMDB.
#![cfg(feature = "lmdb")]

use lumen_mlight::{Host, MemoryHost, Subscript, Value};

fn tmp_dir(tag: &str) -> String {
    let d = std::env::temp_dir().join(format!(
        "lumen_lmdb_test_{}_{}_{}",
        tag,
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let _ = std::fs::remove_dir_all(&d);
    d.to_string_lossy().into_owned()
}

fn ss(s: &str) -> Subscript {
    Subscript::String(s.to_string())
}
fn nn(n: f64) -> Subscript {
    Subscript::Number(n)
}
fn sub_str(s: &Subscript) -> String {
    match s {
        Subscript::String(x) => x.clone(),
        Subscript::Number(n) => {
            if n.fract() == 0.0 {
                format!("{}", *n as i64)
            } else {
                format!("{n}")
            }
        }
    }
}

#[test]
fn roundtrip_y_persistencia() {
    let dir = tmp_dir("roundtrip");
    {
        let mut h = MemoryHost::from_lmdb(&dir).unwrap();
        assert!(h.is_lmdb());
        h.set("TEST", &[ss("a"), nn(1.0)], Value::String("hola".into()))
            .unwrap();
        h.set("TEST", &[ss("a"), nn(2.0)], Value::Number(42.0)).unwrap();
        assert_eq!(
            h.get("TEST", &[ss("a"), nn(1.0)]).unwrap().unwrap().as_string(),
            "hola"
        );
    }
    // Reabrir: los datos viven en LMDB, no en RAM.
    {
        let h = MemoryHost::from_lmdb(&dir).unwrap();
        assert_eq!(
            h.get("TEST", &[ss("a"), nn(1.0)]).unwrap().unwrap().as_string(),
            "hola"
        );
        assert_eq!(
            h.get("TEST", &[ss("a"), nn(2.0)]).unwrap().unwrap().as_string(),
            "42"
        );
        assert!(h.get("TEST", &[ss("nope")]).unwrap().is_none());
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn data_0_1_10_11() {
    let dir = tmp_dir("data");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    assert_eq!(h.data("T", &[]).unwrap(), 0);
    h.set("T", &[ss("x")], Value::String("1".into())).unwrap();
    assert_eq!(h.data("T", &[]).unwrap(), 10);
    assert_eq!(h.data("T", &[ss("x")]).unwrap(), 1);
    h.set("T", &[ss("x"), ss("y")], Value::String("2".into()))
        .unwrap();
    assert_eq!(h.data("T", &[ss("x")]).unwrap(), 11);
    assert_eq!(h.data("T", &[ss("x"), ss("y")]).unwrap(), 1);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn kill_subarbol_cuenta_y_conserva_hermanos() {
    let dir = tmp_dir("kill");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    for i in 0..5 {
        h.set("K", &[ss("a"), nn(i as f64)], Value::String(format!("v{i}")))
            .unwrap();
    }
    h.set("K", &[ss("b")], Value::String("keep".into())).unwrap();
    let n = h.kill("K", &[ss("a")]).unwrap();
    assert_eq!(n, 5);
    assert_eq!(h.data("K", &[ss("a")]).unwrap(), 0);
    assert_eq!(h.get("K", &[ss("b")]).unwrap().unwrap().as_string(), "keep");
    // kill de la ns entera
    h.set("K", &[ss("c"), nn(1.0)], Value::String("c1".into())).unwrap();
    let n2 = h.kill("K", &[]).unwrap();
    assert_eq!(n2, 2); // b + c(1)
    assert_eq!(h.data("K", &[]).unwrap(), 0);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn order_fwd_bwd() {
    let dir = tmp_dir("order");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    for (s, v) in [
        (nn(2.0), "n2"),
        (nn(10.0), "n10"),
        (nn(300.0), "n300"),
        (ss("m"), "sm"),
        (ss("a"), "sa"),
        (ss("z"), "sz"),
    ] {
        h.set("O", &[s], Value::String(v.into())).unwrap();
    }
    // Forward: números (numéricos: 2 < 10 < 300) y luego strings (a < m < z)
    let mut cur: Option<Subscript> = None;
    let mut seq: Vec<String> = Vec::new();
    loop {
        match h.order("O", &[], cur.as_ref(), 1).unwrap() {
            Some(s) => {
                seq.push(sub_str(&s));
                cur = Some(s);
            }
            None => break,
        }
    }
    assert_eq!(seq, vec!["2", "10", "300", "a", "m", "z"]);
    // Backward
    assert_eq!(
        sub_str(&h.order("O", &[], None, -1).unwrap().unwrap()),
        "z"
    );
    assert_eq!(
        sub_str(&h.order("O", &[], Some(&ss("m")), -1).unwrap().unwrap()),
        "a"
    );
    assert_eq!(
        sub_str(&h.order("O", &[], Some(&ss("z")), -1).unwrap().unwrap()),
        "m"
    );
    // Backward desde el primero → None
    assert!(h.order("O", &[], Some(&nn(2.0)), -1).unwrap().is_none());
    // Forward desde el último → None
    assert!(h.order("O", &[], Some(&ss("z")), 1).unwrap().is_none());
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn transacciones_rollback_commit_anidado() {
    let dir = tmp_dir("txn");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    h.set("X", &[ss("k")], Value::String("v0".into())).unwrap();

    // Rollback restaura valor previo y elimina lo nuevo
    h.transaction_start().unwrap();
    h.set("X", &[ss("k")], Value::String("v1".into())).unwrap();
    h.set("X", &[ss("nueva")], Value::String("n".into())).unwrap();
    assert_eq!(h.get("X", &[ss("k")]).unwrap().unwrap().as_string(), "v1");
    h.transaction_rollback().unwrap();
    assert_eq!(h.get("X", &[ss("k")]).unwrap().unwrap().as_string(), "v0");
    assert!(h.get("X", &[ss("nueva")]).unwrap().is_none());

    // Commit mantiene
    h.transaction_start().unwrap();
    h.set("X", &[ss("k")], Value::String("v2".into())).unwrap();
    h.transaction_commit().unwrap();
    assert_eq!(h.get("X", &[ss("k")]).unwrap().unwrap().as_string(), "v2");

    // Anidado: rollback interno deshace solo su nivel
    h.transaction_start().unwrap();
    h.set("X", &[ss("k")], Value::String("v3".into())).unwrap();
    h.transaction_start().unwrap();
    h.set("X", &[ss("k")], Value::String("v4".into())).unwrap();
    h.set("X", &[ss("k2")], Value::String("k2".into())).unwrap();
    h.transaction_rollback().unwrap();
    assert_eq!(h.get("X", &[ss("k")]).unwrap().unwrap().as_string(), "v3");
    assert!(h.get("X", &[ss("k2")]).unwrap().is_none());
    h.transaction_rollback().unwrap();
    assert_eq!(h.get("X", &[ss("k")]).unwrap().unwrap().as_string(), "v2");

    // KILL dentro de txn + rollback restaura el subárbol
    h.set("X", &[ss("t"), nn(1.0)], Value::String("t1".into())).unwrap();
    h.set("X", &[ss("t"), nn(2.0)], Value::String("t2".into())).unwrap();
    h.transaction_start().unwrap();
    h.kill("X", &[ss("t")]).unwrap();
    assert_eq!(h.data("X", &[ss("t")]).unwrap(), 0);
    h.transaction_rollback().unwrap();
    assert_eq!(
        h.get("X", &[ss("t"), nn(1.0)]).unwrap().unwrap().as_string(),
        "t1"
    );
    assert_eq!(
        h.get("X", &[ss("t"), nn(2.0)]).unwrap().unwrap().as_string(),
        "t2"
    );
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn numeros_con_ff_en_mantisa_no_cortan_la_enumeracion() {
    // Regresión 20-sep-2026: f64-BE con byte 0xFF dentro (p.ej. from_bits
    // 0x40B0FF0000000000) hacía que el decode lo tratara como legacy y la
    // enumeración de $O se cortara. El boundary de saltos es estructural.
    let dir = tmp_dir("ffbytes");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    let x = f64::from_bits(0x40B0FF0000000000);
    for i in 0..30u64 {
        h.set("FF", &[nn(i as f64)], Value::String(format!("v{i}"))).unwrap();
    }
    h.set("FF", &[nn(x)], Value::String("vx".into())).unwrap();
    for i in 40..60u64 {
        h.set("FF", &[nn(i as f64)], Value::String(format!("v{i}"))).unwrap();
    }
    let mut cur: Option<Subscript> = None;
    let mut count = 0usize;
    loop {
        match h.order("FF", &[], cur.as_ref(), 1).unwrap() {
            Some(s) => { count += 1; cur = Some(s); }
            None => break,
        }
    }
    assert_eq!(count, 51, "la enumeración no debe cortarse con nums FF en mantisa");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn order_cache_invalidada_por_writes() {
    let dir = tmp_dir("cache");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    h.set("C", &[ss("a")], Value::String("1".into())).unwrap();
    h.set("C", &[ss("b")], Value::String("2".into())).unwrap();
    // primer $O → construye la caché de hijos
    assert_eq!(sub_str(&h.order("C", &[], None, 1).unwrap().unwrap()), "a");
    // nuevo hijo → la caché debe invalidarse y verlo
    h.set("C", &[ss("c")], Value::String("3".into())).unwrap();
    assert_eq!(
        sub_str(&h.order("C", &[], Some(&ss("b")), 1).unwrap().unwrap()),
        "c"
    );
    // kill → invalidación
    h.kill("C", &[ss("c")]).unwrap();
    assert!(h.order("C", &[], Some(&ss("b")), 1).unwrap().is_none());
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn orden_equivalente_ram_vs_lmdb() {
    let dir = tmp_dir("equiv");
    let mut ram = MemoryHost::default();
    let mut lm = MemoryHost::from_lmdb(&dir).unwrap();
    let subs: Vec<Subscript> = vec![
        nn(2.0),
        nn(10.0),
        nn(0.0),
        nn(0.5),
        ss("a"),
        ss("b"),
        ss("a2"),
        ss("A"),
        ss(""),
    ];
    for s in &subs {
        ram.set("E", std::slice::from_ref(s), Value::String("x".into())).unwrap();
        lm.set("E", std::slice::from_ref(s), Value::String("x".into())).unwrap();
    }
    for dirn in [1i32, -1] {
        let mut cur: Option<Subscript> = None;
        for _step in 0..32 {
            let a = ram.order("E", &[], cur.as_ref(), dirn).unwrap();
            let b = lm.order("E", &[], cur.as_ref(), dirn).unwrap();
            assert_eq!(
                a.as_ref().map(|x| sub_str(x)),
                b.as_ref().map(|x| sub_str(x)),
                "divergencia RAM↔LMDB en dir={} cur={:?}",
                dirn,
                cur.as_ref().map(|x| sub_str(x))
            );
            match a {
                Some(s) => cur = Some(s),
                None => break,
            }
        }
    }
    let _ = std::fs::remove_dir_all(&dir);
}
