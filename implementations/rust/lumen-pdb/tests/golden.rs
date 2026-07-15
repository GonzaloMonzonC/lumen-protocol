//! Tests golden: encode_subkey Rust DEBE producir los mismos bytes que
//! Python (tests/golden_subkey.json, generado por pdb_tools.encode_subkey).

use lumen_pdb::globals::Pdb;
use lumen_pdb::subkey::{decode_subkey, encode_subkey, Sub};
use serde_json::Value;

fn load_golden() -> Vec<(Vec<Sub>, Vec<u8>)> {
    let raw = include_str!("golden_subkey.json");
    let parsed: Value = serde_json::from_str(raw).unwrap();
    let mut out = Vec::new();
    for case in parsed.as_array().unwrap() {
        let subs: Vec<Sub> = case["subs"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| match v {
                Value::Null => Sub::Null,
                Value::Number(n) => Sub::Num(n.as_f64().unwrap()),
                Value::String(s) => Sub::Str(s.clone()),
                other => panic!("tipo inesperado en golden: {other:?}"),
            })
            .collect();
        let hex = case["hex"].as_str().unwrap();
        let bytes: Vec<u8> = (0..hex.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
            .collect();
        out.push((subs, bytes));
    }
    out
}

#[test]
fn encode_matches_python_golden() {
    let cases = load_golden();
    assert!(cases.len() >= 30, "golden incompleto");
    for (subs, expected) in &cases {
        let got = encode_subkey(subs);
        assert_eq!(
            &got,
            expected,
            "encode divergente para {subs:?}: got {} expected {}",
            hex(&got),
            hex(expected)
        );
    }
}

#[test]
fn decode_roundtrip() {
    for (subs, bytes) in &load_golden() {
        let decoded = decode_subkey(bytes);
        assert_eq!(decoded.len(), subs.len(), "niveles distintos para {subs:?}");
        for (a, b) in subs.iter().zip(decoded.iter()) {
            match (a, b) {
                (Sub::Num(x), Sub::Num(y)) => {
                    assert!(
                        x == y || (x.is_infinite() && y.is_infinite() && x.signum() == y.signum()),
                        "num {x} != {y}"
                    )
                }
                (Sub::Str(x), Sub::Str(y)) => assert_eq!(x, y),
                (Sub::Null, Sub::Null) => {}
                other => panic!("tipos divergentes: {other:?}"),
            }
        }
    }
}

#[test]
fn collation_quirks_pinned() {
    // números < strings
    assert!(encode_subkey(&[Sub::Num(1e300)]) < encode_subkey(&[Sub::Str("A".into())]));
    // prefijo ordena DESPUÉS de su extensión: "ab" < "a"
    assert!(encode_subkey(&[Sub::Str("ab".into())]) < encode_subkey(&[Sub::Str("a".into())]));
    // "" es la mayor de las strings
    assert!(encode_subkey(&[Sub::Str("z".into())]) < encode_subkey(&[Sub::Str("".into())]));
    // orden numérico correcto con negativos y ceros
    let vals = [-1e300, -1.0, -0.0, 0.0, 0.5, 42.0, 1e300];
    let encs: Vec<_> = vals
        .iter()
        .map(|v| encode_subkey(&[Sub::Num(*v)]))
        .collect();
    let mut sorted = encs.clone();
    sorted.sort();
    assert_eq!(encs, sorted);
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

// ── Operaciones sobre redb ──

fn subs(v: &[&str]) -> Vec<u8> {
    encode_subkey(&v.iter().map(|s| Sub::Str((*s).into())).collect::<Vec<_>>())
}

#[test]
fn globals_ops_semantics() {
    let dir = std::env::temp_dir().join(format!("lumen-pdb-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("ops.redb");
    let _ = std::fs::remove_file(&path);
    let db = Pdb::open(path.to_str().unwrap()).unwrap();

    // SET/GET
    db.set("TEST", &subs(&["a"]), b"\"v1\"").unwrap();
    db.set("TEST", &subs(&["a", "b"]), b"\"v2\"").unwrap();
    db.set("TEST", &subs(&["c"]), b"\"v3\"").unwrap();
    assert_eq!(db.get("TEST", &subs(&["a"])).unwrap().unwrap(), b"\"v1\"");
    assert!(db.get("TEST", &subs(&["zz"])).unwrap().is_none());
    assert!(db.get("NOEXISTE", &subs(&["a"])).unwrap().is_none());

    // $DATA: 11 (valor+hijos), 1 (valor), 10 (solo hijos), 0
    assert_eq!(db.data("TEST", &subs(&["a"])).unwrap(), 11);
    assert_eq!(db.data("TEST", &subs(&["c"])).unwrap(), 1);
    db.set("TEST", &subs(&["d", "x"]), b"1").unwrap();
    assert_eq!(db.data("TEST", &subs(&["d"])).unwrap(), 10);
    assert_eq!(db.data("TEST", &subs(&["nada"])).unwrap(), 0);

    // $ORDER hacia delante: primer nivel = a, c, d
    let first = db.order("TEST", &[], None, 1).unwrap().unwrap();
    assert_eq!(decode_subkey(&first), vec![Sub::Str("a".into())]);
    let second = db.order("TEST", &[], Some(&first), 1).unwrap().unwrap();
    assert_eq!(decode_subkey(&second), vec![Sub::Str("c".into())]);
    let third = db.order("TEST", &[], Some(&second), 1).unwrap().unwrap();
    assert_eq!(decode_subkey(&third), vec![Sub::Str("d".into())]);
    assert!(db.order("TEST", &[], Some(&third), 1).unwrap().is_none());

    // $ORDER hacia atrás
    let last = db.order("TEST", &[], None, -1).unwrap().unwrap();
    assert_eq!(decode_subkey(&last), vec![Sub::Str("d".into())]);
    let prev = db.order("TEST", &[], Some(&last), -1).unwrap().unwrap();
    assert_eq!(decode_subkey(&prev), vec![Sub::Str("c".into())]);

    // $ORDER en subnivel
    let child = db.order("TEST", &subs(&["a"]), None, 1).unwrap().unwrap();
    assert_eq!(decode_subkey(&child), vec![Sub::Str("b".into())]);

    // SQLite NULL se migra como raw vacío: nodo estructural, no valor.
    db.set("TEST", &subs(&["struct"]), b"").unwrap();
    db.set("TEST", &subs(&["struct", "x"]), b"1").unwrap();
    assert_eq!(db.data("TEST", &subs(&["struct"])).unwrap(), 10);

    // $INCREMENT
    assert_eq!(db.incr("CNT", &subs(&["n"]), 1.0).unwrap(), 1.0);
    assert_eq!(db.incr("CNT", &subs(&["n"]), 2.5).unwrap(), 3.5);
    assert_eq!(db.get("CNT", &subs(&["n"])).unwrap().unwrap(), b"3.5");

    // MERGE
    let n = db
        .merge("TEST", &subs(&["copia"]), "TEST", &subs(&["a"]))
        .unwrap();
    assert_eq!(n, 2); // nodo + 1 hijo
    assert_eq!(
        db.get("TEST", &subs(&["copia", "b"])).unwrap().unwrap(),
        b"\"v2\""
    );

    // KILL subárbol
    let killed = db.kill("TEST", &subs(&["a"])).unwrap();
    assert_eq!(killed, 2);
    assert_eq!(db.data("TEST", &subs(&["a"])).unwrap(), 0);
    assert!(db.get("TEST", &subs(&["c"])).unwrap().is_some()); // hermano intacto

    // orden mixto numérico/string: números primero
    db.set("MIX", &encode_subkey(&[Sub::Num(2.0)]), b"1")
        .unwrap();
    db.set("MIX", &encode_subkey(&[Sub::Str("a".into())]), b"1")
        .unwrap();
    db.set("MIX", &encode_subkey(&[Sub::Num(-1.0)]), b"1")
        .unwrap();
    let f = db.order("MIX", &[], None, 1).unwrap().unwrap();
    assert_eq!(decode_subkey(&f), vec![Sub::Num(-1.0)]);

    let _ = std::fs::remove_dir_all(&dir);
}
