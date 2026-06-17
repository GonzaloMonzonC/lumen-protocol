//! WASM bindings — compile with `wasm-pack build --features wasm`
//!
//! Exposes `lumen_compress` and `lumen_decompress` to JavaScript
//! via wasm-bindgen.  Input/output are plain `Uint8Array` / `String`
//! — no raw pointers, no manual free.
//!
//! ## Build
//!
//! ```bash
//! wasm-pack build --target web --features wasm
//! # or for bundlers (webpack, vite, etc):
//! wasm-pack build --target bundler --features wasm
//! ```
//!
//! ## Usage from JS
//!
//! ```javascript
//! import init, { lumen_compress, lumen_decompress, lumen_version } from "./pkg/lumen.js";
//!
//! await init();
//!
//! const json = JSON.stringify({ tool: "search", arguments: { query: "hello" } });
//! const compressed = lumen_compress(json);  // Uint8Array
//! const decompressed = lumen_decompress(compressed);  // string (JSON)
//! ```

use wasm_bindgen::prelude::*;

use crate::compress;

// ── Public WASM API ────────────────────────────────────────────────────────

/// Version string: "0.1.0"
#[wasm_bindgen]
pub fn lumen_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

/// Compress a JSON string into LUMEN compact binary.
///
/// Returns a `Uint8Array` with the compressed LUMEN binary.
/// Throws a JS error if the JSON is invalid.
#[wasm_bindgen]
pub fn lumen_compress(json: &str) -> Result<Vec<u8>, JsValue> {
    let value: serde_json::Value = serde_json::from_str(json).map_err(|e| {
        JsValue::from_str(&format!("JSON parse error: {e}"))
    })?;

    Ok(compress::compress(&value, None))
}

/// Decompress LUMEN binary into a JSON string.
///
/// Returns a JSON string.  Throws a JS error if the binary is malformed.
#[wasm_bindgen]
pub fn lumen_decompress(data: &[u8]) -> Result<String, JsValue> {
    let value = compress::decompress(data, None).ok_or_else(|| {
        JsValue::from_str("decompress error: malformed LUMEN binary")
    })?;

    serde_json::to_string(&value).map_err(|e| {
        JsValue::from_str(&format!("JSON serialize error: {e}"))
    })
}

/// Get the last error message (always returns None in WASM — errors are
/// returned directly via Result types).
#[wasm_bindgen]
pub fn lumen_last_error() -> Option<String> {
    None
}

// ═══ Tests ═════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wasm_roundtrip_simple() {
        let json = r#"{"tool":"search","arguments":{"query":"hello"}}"#;
        let compressed = lumen_compress(json).unwrap();
        let decompressed = lumen_decompress(&compressed).unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&decompressed).unwrap();
        assert_eq!(parsed["tool"], "search");
    }

    #[test]
    fn wasm_compress_invalid_json() {
        let result = lumen_compress("not json");
        assert!(result.is_err());
    }

    #[test]
    fn wasm_decompress_invalid_binary() {
        let result = lumen_decompress(&[0xFF, 0xFF, 0xFF]);
        assert!(result.is_err());
    }
}
