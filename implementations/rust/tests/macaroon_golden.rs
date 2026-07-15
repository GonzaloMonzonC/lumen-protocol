//! Golden cross-language: el mismo macaroon debe producir bytes idénticos
//! en Rust y en Python (implementations/mcp-servers/pdb/pdb_macaroon.py).
//!
//! El hex de referencia se generó con pdb_macaroon.py usando la clave
//! determinista 0x00..0x1f. Si este test falla, los dos ports han divergido.

use lumen::macaroon::{caveats, Macaroon};

const ROOT_KEY: [u8; 32] = [
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x0e,
    0x0f, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17, 0x18, 0x19, 0x1a, 0x1b, 0x1c, 0x1d,
    0x1e, 0x1f,
];

/// Encoded bytes producidos por pdb_macaroon.py con la misma clave/caveats.
const PYTHON_GOLDEN_HEX: &str = "0108676f6c64656e2d31096c756d656e2d70646203106e735f707265666978203d2054455354096f70203d207265616413657870697279203c20323033302d30312d303174104972838bedda95a767a96f35769670f8bb5ab4cd0e436039a7c447eab0f3";

fn hex_decode(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

#[test]
fn rust_encodes_identical_to_python() {
    let mac = Macaroon::create(&ROOT_KEY, "golden-1", "lumen-pdb")
        .attenuate("ns_prefix = TEST")
        .attenuate(&caveats::read_only())
        .attenuate(&caveats::expiry_before("2030-01-01"));

    let encoded = mac.encode();
    assert_eq!(
        encoded,
        hex_decode(PYTHON_GOLDEN_HEX),
        "encode Rust ≠ encode Python — los ports han divergido"
    );
}

#[test]
fn rust_verifies_python_token() {
    let data = hex_decode(PYTHON_GOLDEN_HEX);
    let mac = Macaroon::decode(&data).expect("token Python debe decodificar en Rust");

    assert_eq!(mac.id, "golden-1");
    assert_eq!(mac.location, "lumen-pdb");
    assert_eq!(mac.caveats.len(), 3);

    // Verificación completa (expiry 2030 aún válido; caveats PDB aceptados)
    assert!(mac.verify_with_time(&ROOT_KEY, 1_752_000_000, |c| {
        c.starts_with("ns_prefix = ") || caveats::is_read_only(c)
    }));

    // Firma manipulada → rechazo
    let mut tampered = data.clone();
    let n = tampered.len();
    tampered[n - 1] ^= 0x01;
    let bad = Macaroon::decode(&tampered).unwrap();
    assert!(!bad.verify_with_time(&ROOT_KEY, 1_752_000_000, |_| true));
}
