//! Tests de integración del backend LMDB de MemoryHost (feature "lmdb").
//!
//! Ejecutar: cargo test --features lmdb --test lmdb_host
//!
//! Cubre: roundtrip + persistencia real (reabrir env), $D (0/1/10/11),
//! KILL de subárbol (conteo), $O forward/backward (cursor), transacciones
//! anidables con rollback (undo-log), y equivalencia del orden RAM↔LMDB.
#![cfg(feature = "lmdb")]

use lumen_mlight::lmdb_store::LmdbStore;
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
    let mut saw_x = false;
    loop {
        match h.order("FF", &[], cur.as_ref(), 1).unwrap() {
            Some(s) => {
                if let Subscript::Number(v) = &s {
                    if *v == x {
                        saw_x = true;
                    }
                }
                count += 1;
                cur = Some(s);
            }
            None => break,
        }
    }
    assert_eq!(count, 51, "la enumeración no debe cortarse con nums FF en mantisa");
    assert!(saw_x, "el num con 0xFF en mantisa debe decodificar como Number (no String basura)");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn fila_legacy_ascii_y_canonica_conviven() {
    // Regresión 2026-09-20 (fix decoder): \x01 + ascii + \xff (formato viejo)
    // sigue leyéndose como Number si parsea, y convive con el canónico 01+8B.
    let dir = tmp_dir("legacy");
    let mut store = LmdbStore::open(&dir).unwrap();
    let mut k_legacy = vec![0x01u8];
    k_legacy.extend_from_slice(b"123");
    k_legacy.push(0xFF);
    k_legacy.push(0xFF);
    let mut k_canon = vec![0x01u8];
    k_canon.extend_from_slice(&7.0f64.to_be_bytes());
    k_canon.push(0xFF);
    store
        .put_many(&[
            ("LG".to_string(), k_legacy, b"v123".to_vec()),
            ("LG".to_string(), k_canon, b"v7".to_vec()),
        ])
        .unwrap();
    drop(store);
    let h = MemoryHost::from_lmdb(&dir).unwrap();
    assert_eq!(h.order("LG", &[], None, 1).unwrap(), Some(nn(7.0)));
    assert_eq!(
        h.order("LG", &[], Some(&nn(7.0)), 1).unwrap(),
        Some(nn(123.0)),
        "el legacy '123' debe seguir viéndose como Number(123) en $O"
    );
    // Limitación conocida de LMDB: una fila legacy se ENUMERA con su valor
    // decodificado, pero $G con la clave canónica no la encuentra (la clave
    // almacenada son los bytes legacy; no hay filas legacy en producción).
    assert!(h.get("LG", &[nn(123.0)]).unwrap().is_none());
    assert!(h.get("LG", &[nn(7.0)]).unwrap().is_some());
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

#[test]
fn tx_batching_write_behind() {
    // #3 batching (20-sep-2026): los sets dentro de TS/TC se acumulan en memoria
    // (read-your-writes) y se aplican en UNA write-txn al TCOMMIT externo.
    let dir = tmp_dir("txbatch");
    {
        let mut h = MemoryHost::from_lmdb(&dir).unwrap();
        h.set("B", &[ss("k")], Value::String("v0".into())).unwrap();
        h.transaction_start().unwrap();
        for i in 0..50u64 {
            h.set("B", &[nn(i as f64)], Value::String(format!("n{i}"))).unwrap();
        }
        h.set("B", &[ss("k")], Value::String("v1".into())).unwrap();
        // read-your-writes dentro de la txn
        assert_eq!(h.get("B", &[ss("k")]).unwrap().unwrap().as_string(), "v1");
        assert_eq!(h.get("B", &[nn(49.0)]).unwrap().unwrap().as_string(), "n49");
        // $D y $O también ven los pendientes
        assert_eq!(h.data("B", &[nn(3.0)]).unwrap(), 1);
        assert_eq!(h.order("B", &[], None, 1).unwrap(), Some(nn(0.0)));
        assert_eq!(h.transaction_level(), 1);
        h.transaction_commit().unwrap();
        assert_eq!(h.transaction_level(), 0);
    }
    // Persistencia real tras reabrir el env
    {
        let h = MemoryHost::from_lmdb(&dir).unwrap();
        assert_eq!(h.get("B", &[ss("k")]).unwrap().unwrap().as_string(), "v1");
        assert_eq!(h.get("B", &[nn(49.0)]).unwrap().unwrap().as_string(), "n49");
        assert_eq!(h.get("B", &[nn(0.0)]).unwrap().unwrap().as_string(), "n0");
    }
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn tx_rollback_descarta_y_anidado() {
    let dir = tmp_dir("txrb2");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    h.set("R", &[ss("a")], Value::String("orig".into())).unwrap();
    h.set("R", &[ss("b"), nn(1.0)], Value::String("b1".into())).unwrap();
    h.set("R", &[ss("b"), nn(2.0)], Value::String("b2".into())).unwrap();
    // rollback descarta writes Y deletes (sin tocar disco)
    h.transaction_start().unwrap();
    h.set("R", &[ss("a")], Value::String("tmp".into())).unwrap();
    h.set("R", &[ss("nueva")], Value::String("x".into())).unwrap();
    let n = h.kill("R", &[ss("b")]).unwrap();
    assert!(n >= 2, "el kill en txn debe contar las claves afectadas ({n})");
    assert_eq!(h.data("R", &[ss("b"), nn(1.0)]).unwrap(), 0);
    assert_eq!(
        h.order("R", &[], Some(&ss("a")), 1).unwrap(),
        Some(ss("nueva")),
        "en txn: 'b' muerto en overlay, 'nueva' viva"
    );
    h.transaction_rollback().unwrap();
    assert_eq!(h.get("R", &[ss("a")]).unwrap().unwrap().as_string(), "orig");
    assert!(h.get("R", &[ss("nueva")]).unwrap().is_none());
    assert_eq!(h.get("R", &[ss("b"), nn(1.0)]).unwrap().unwrap().as_string(), "b1");
    assert_eq!(
        h.order("R", &[], Some(&ss("a")), 1).unwrap(),
        Some(ss("b")),
        "tras rollback: 'b' restaurada, 'nueva' ya no está"
    );
    // anidado: rollback interno → queda el estado del externo; commit externo aplica
    h.transaction_start().unwrap();
    h.set("R", &[ss("a")], Value::String("n1".into())).unwrap();
    h.transaction_start().unwrap();
    h.set("R", &[ss("a")], Value::String("n2".into())).unwrap();
    assert_eq!(h.get("R", &[ss("a")]).unwrap().unwrap().as_string(), "n2");
    h.transaction_rollback().unwrap();
    assert_eq!(h.get("R", &[ss("a")]).unwrap().unwrap().as_string(), "n1");
    h.transaction_commit().unwrap();
    assert_eq!(h.get("R", &[ss("a")]).unwrap().unwrap().as_string(), "n1");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn sysinfo_overlay_ram_sobre_store() {
    // Estreno neferu (20-sep-2026): el host siembra ^SYSINFO (nodo/version/
    // routines_dir/filas…) SOLO en el mapa RAM. En modo LMDB el mapa debe
    // actuar de overlay de lectura ($G/$D/$O) para ese namespace.
    let dir = tmp_dir("sysinfo_overlay");
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    // store: una clave NO gestionada bajo SYSINFO (p.ej. fuente) y una ns normal
    h.set("SYSINFO", &[ss("fuente"), ss("X"), nn(1.0)], Value::String("src".into()))
        .unwrap();
    h.set("OTRA", &[ss("k")], Value::String("v".into())).unwrap();
    // overlay RAM (lo que hace seed_sysinfo con si_put)
    h.values.insert(
        ("SYSINFO".to_string(), vec![ss("nodo")]),
        Value::String("NODO-X".into()),
    );
    h.values.insert(
        ("SYSINFO".to_string(), vec![ss("routines_dir")]),
        Value::String("routines".into()),
    );
    // $G: overlay gana; el store sigue visible
    assert_eq!(h.get("SYSINFO", &[ss("nodo")]).unwrap().unwrap().as_string(), "NODO-X");
    assert_eq!(h.get("SYSINFO", &[ss("routines_dir")]).unwrap().unwrap().as_string(), "routines");
    assert_eq!(
        h.get("SYSINFO", &[ss("fuente"), ss("X"), nn(1.0)]).unwrap().unwrap().as_string(),
        "src"
    );
    // $D: unión (semilla sola, store solo-hijos, ns ajena intacta)
    assert_eq!(h.data("SYSINFO", &[ss("nodo")]).unwrap(), 1);
    assert_eq!(h.data("SYSINFO", &[ss("fuente")]).unwrap(), 10);
    assert_eq!(h.data("OTRA", &[ss("k")]).unwrap(), 1);
    // $O: unión ordenada canónica (fuente < nodo < routines_dir)
    assert_eq!(sub_str(&h.order("SYSINFO", &[], None, 1).unwrap().unwrap()), "fuente");
    assert_eq!(
        sub_str(&h.order("SYSINFO", &[], Some(&ss("fuente")), 1).unwrap().unwrap()),
        "nodo"
    );
    assert_eq!(sub_str(&h.order("SYSINFO", &[], None, -1).unwrap().unwrap()), "routines_dir");
    // set/kill en SYSINFO: espejo inmediato en el overlay
    h.set("SYSINFO", &[ss("nodo")], Value::String("NODO-Y".into())).unwrap();
    assert_eq!(h.get("SYSINFO", &[ss("nodo")]).unwrap().unwrap().as_string(), "NODO-Y");
    h.kill("SYSINFO", &[ss("nodo")]).unwrap();
    assert!(h.get("SYSINFO", &[ss("nodo")]).unwrap().is_none());
    assert_eq!(h.data("SYSINFO", &[ss("nodo")]).unwrap(), 0);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn order_numero_multinivel_qpdb_no_se_cuelga() {
    // Regresión 22-sep-2026 (^CHANGES del PC): los subkeys escritos por
    // qpdb/poli terminan CADA sub con \xff — números incluidos (01+8B+FF).
    // El salto de $O quedaba como prefijo de la propia clave → la enumeración
    // giraba sin avanzar (bucle infinito con 103k hijos). Debe completar y
    // devolver exactamente los hijos, en orden canónico.
    let dir = tmp_dir("order_numff");
    let num_a = -1.78832053943463e18f64;
    let num_b = 3.5f64;
    {
        let mut store = LmdbStore::open(&dir).unwrap();
        let mut sk_a = vec![0x01u8];
        sk_a.extend_from_slice(&num_a.to_be_bytes());
        sk_a.push(0xFF);
        sk_a.extend_from_slice(b"\x02SET\xFF");
        sk_a.extend_from_slice(b"\x02X\xFF");
        let mut sk_b = vec![0x01u8];
        sk_b.extend_from_slice(&num_b.to_be_bytes());
        sk_b.push(0xFF);
        sk_b.extend_from_slice(b"\x02SET\xFF");
        let sk_c = b"\x02zeta\xFF".to_vec();
        store
            .put_many(&[
                ("CHANGES".to_string(), sk_a, b"a".to_vec()),
                ("CHANGES".to_string(), sk_b, b"b".to_vec()),
                ("CHANGES".to_string(), sk_c, b"c".to_vec()),
            ])
            .unwrap();
    }
    let h = MemoryHost::from_lmdb(&dir).unwrap();
    let mut seq: Vec<Subscript> = Vec::new();
    let mut cur: Option<Subscript> = None;
    loop {
        match h.order("CHANGES", &[], cur.as_ref(), 1).unwrap() {
            Some(s) => {
                cur = Some(s.clone());
                seq.push(s);
            }
            None => break,
        }
        assert!(seq.len() <= 3, "bucle en $O: se enumeraron más hijos que claves hay");
    }
    assert_eq!(seq.len(), 3, "enumeración completa sin duplicados");
    // Orden canónico: números por VALOR (-1.78e18 < 3.5) y luego strings
    assert_eq!(seq[0], Subscript::Number(num_a));
    assert_eq!(seq[1], Subscript::Number(num_b));
    assert_eq!(seq[2], Subscript::String("zeta".to_string()));
    // backward: del final al primero
    assert_eq!(h.order("CHANGES", &[], None, -1).unwrap(), Some(ss("zeta")));
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn compat_lectura_legacy_python() {
    // Regresión 22-sep-2026 (datos REALES del PC/nodos convertidos a LMDB):
    // las filas escritas por qpdb/poli/python usan la variante legacy — 0xFF
    // tras CADA número y SIN terminador final de nodo — y el motor no las
    // veía en $G/$D exactos (^KANBAN("meta") daba D=0). Deben leerse, y el
    // KILL debe cubrir nodo+subárbol en AMBAS variantes.
    let dir = tmp_dir("legacy_compat");
    let num = -1.78832053943463e18f64;
    // subkey legacy para ^CHANGES(<num>,"SET","X") y su hijo ("X","sub")
    let mut sk = vec![0x01u8];
    sk.extend_from_slice(&num.to_be_bytes());
    sk.push(0xFF);
    sk.extend_from_slice(b"\x02SET\xFF");
    sk.extend_from_slice(b"\x02X\xFF");
    let mut sk_hijo = sk.clone();
    sk_hijo.extend_from_slice(b"\x02sub\xFF");
    {
        let mut store = LmdbStore::open(&dir).unwrap();
        store
            .put_many(&[
                ("CHANGES".to_string(), sk, b"v-nodo".to_vec()),
                ("CHANGES".to_string(), sk_hijo, b"v-hijo".to_vec()),
                // caso real ^KANBAN("meta"): valor en clave legacy sin FF final
                (
                    "KANBAN".to_string(),
                    b"\x02meta\xFF".to_vec(),
                    b"{\"total\":212}".to_vec(),
                ),
            ])
            .unwrap();
    }
    let mut h = MemoryHost::from_lmdb(&dir).unwrap();
    // $G exacto DEBE encontrar la fila legacy (antes: None → "" en M)
    assert_eq!(
        h.get("CHANGES", &[nn(num), ss("SET"), ss("X")])
            .unwrap()
            .unwrap()
            .as_string(),
        "v-nodo"
    );
    assert_eq!(
        h.get("KANBAN", &[ss("meta")]).unwrap().unwrap().as_string(),
        "{\"total\":212}"
    );
    // $D: nodo con valor y descendiente → 11; con solo descendientes → 10
    assert_eq!(h.data("CHANGES", &[nn(num), ss("SET"), ss("X")]).unwrap(), 11);
    assert_eq!(h.data("CHANGES", &[nn(num), ss("SET")]).unwrap(), 10);
    assert_eq!(h.data("KANBAN", &[ss("meta")]).unwrap(), 1);
    // set escribe la variante canónica; get canónica-primero la ve al momento
    h.set(
        "CHANGES",
        &[nn(num), ss("SET"), ss("X")],
        Value::String("v2".into()),
    )
    .unwrap();
    assert_eq!(
        h.get("CHANGES", &[nn(num), ss("SET"), ss("X")])
            .unwrap()
            .unwrap()
            .as_string(),
        "v2"
    );
    // kill: canónico (v2) + legacy (v-nodo) + hijo legacy = 3 claves
    assert_eq!(h.kill("CHANGES", &[nn(num), ss("SET"), ss("X")]).unwrap(), 3);
    assert_eq!(h.data("CHANGES", &[nn(num), ss("SET"), ss("X")]).unwrap(), 0);
    let _ = std::fs::remove_dir_all(&dir);
}
