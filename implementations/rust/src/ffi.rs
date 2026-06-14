//! C FFI — stable ABI for 20+ languages.
//!
//! Every function takes ptr+len (never assumes null-termination),
//! returns 0 on success / -1 on error, and uses out-parameters for
//! heap-allocated results. Callers must call `lumen_free` to release
//! returned buffers.
//!
//! ## Quick example (C)
//!
//! ```c
//! #include "lumen.h"
//!
//! uint8_t *out = NULL;
//! size_t out_len = 0;
//! if (lumen_compress(json, strlen(json), &out, &out_len) == 0) {
//!     send(sock, out, out_len, 0);
//!     lumen_free(out, out_len);
//! }
//! ```

use std::os::raw::c_char;
use std::sync::Mutex;

use crate::compress;

// ── Last-error storage ─────────────────────────────────────────────────────

static LAST_ERROR: Mutex<Option<String>> = Mutex::new(None);

fn set_error(msg: String) {
    if let Ok(mut guard) = LAST_ERROR.lock() {
        // Truncate to avoid unbounded growth
        if msg.len() > 512 {
            *guard = Some(msg[..512].to_string());
        } else {
            *guard = Some(msg);
        }
    }
}

fn take_error() -> Option<String> {
    LAST_ERROR.lock().ok().and_then(|mut g| g.take())
}

// ── Public API ─────────────────────────────────────────────────────────────

/// Version: (major << 24) | (minor << 16) | (patch << 8) | 0
/// e.g. 0x00010000 = v0.1.0
#[no_mangle]
pub extern "C" fn lumen_version() -> u32 {
    0x0001_0000 // v0.1.0
}

/// Get the last error message (thread-safe).
///
/// Returns a null-terminated UTF-8 string owned by the library.
/// The pointer is valid until the next call to any lumen_* function
/// on the same thread. Returns NULL if no error.
#[no_mangle]
pub extern "C" fn lumen_error_message() -> *const c_char {
    use std::ffi::CString;

    thread_local! {
        static LAST_MSG: std::cell::RefCell<Option<CString>> =
            std::cell::RefCell::new(None);
    }
    let msg = take_error();
    let ptr: *const c_char = match &msg {
        Some(s) => {
            let cs = CString::new(s.as_str()).unwrap_or_else(|_| CString::new("encoding error").unwrap());
            let p = cs.as_ptr();
            LAST_MSG.with(|cell| *cell.borrow_mut() = Some(cs));
            p
        }
        None => std::ptr::null(),
    };
    ptr
}

/// Compress a JSON string into LUMEN compact binary.
///
/// - `json_ptr`, `json_len`: UTF-8 JSON input (not necessarily null-terminated).
/// - `out_ptr`: receives pointer to heap-allocated compressed buffer.
/// - `out_len`: receives length of compressed buffer in bytes.
///
/// Returns 0 on success, -1 on error (call `lumen_error_message()` for details).
/// On success the caller MUST free `*out_ptr` with `lumen_free()`.
#[no_mangle]
pub extern "C" fn lumen_compress(
    json_ptr: *const u8,
    json_len: usize,
    out_ptr: *mut *mut u8,
    out_len: *mut usize,
) -> i32 {
    if json_ptr.is_null() || out_ptr.is_null() || out_len.is_null() {
        set_error("null pointer argument".into());
        return -1;
    }

    let json_bytes = unsafe { std::slice::from_raw_parts(json_ptr, json_len) };

    let value: serde_json::Value = match serde_json::from_slice(json_bytes) {
        Ok(v) => v,
        Err(e) => {
            set_error(format!("JSON parse error: {e}"));
            return -1;
        }
    };

    let compressed = compress::compress(&value);

    // Convert Vec<u8> into a raw pointer+len that the caller owns.
    let mut boxed = compressed.into_boxed_slice();
    let (ptr, len) = (boxed.as_mut_ptr(), boxed.len());
    std::mem::forget(boxed); // caller owns it now

    unsafe {
        *out_ptr = ptr;
        *out_len = len;
    }
    0
}

/// Decompress LUMEN binary into a JSON string.
///
/// - `data_ptr`, `data_len`: LUMEN compact binary input.
/// - `out_ptr`: receives pointer to heap-allocated JSON UTF-8 string.
/// - `out_len`: receives length of JSON string in bytes.
///
/// Returns 0 on success, -1 on error. Caller MUST free `*out_ptr` with `lumen_free()`.
#[no_mangle]
pub extern "C" fn lumen_decompress(
    data_ptr: *const u8,
    data_len: usize,
    out_ptr: *mut *mut u8,
    out_len: *mut usize,
) -> i32 {
    if data_ptr.is_null() || out_ptr.is_null() || out_len.is_null() {
        set_error("null pointer argument".into());
        return -1;
    }

    let data = unsafe { std::slice::from_raw_parts(data_ptr, data_len) };

    let value = match compress::decompress(data) {
        Some(v) => v,
        None => {
            set_error("decompress error: malformed LUMEN binary".into());
            return -1;
        }
    };

    let json = serde_json::to_string(&value).unwrap_or_else(|e| {
        set_error(format!("JSON serialize error: {e}"));
        "{}".to_string()
    });

    let mut boxed = json.into_bytes().into_boxed_slice();
    let (ptr, len) = (boxed.as_mut_ptr(), boxed.len());
    std::mem::forget(boxed);

    unsafe {
        *out_ptr = ptr;
        *out_len = len;
    }
    0
}

/// Free a buffer previously returned by `lumen_compress` or `lumen_decompress`.
///
/// Safe to call with NULL (no-op).  `len` must match the length returned
/// by the corresponding function.
#[no_mangle]
pub extern "C" fn lumen_free(ptr: *mut u8, len: usize) {
    if ptr.is_null() || len == 0 {
        return;
    }
    unsafe {
        // Reconstruct the Box<[u8]> so Rust drops it properly.
        let _ = Box::from_raw(std::slice::from_raw_parts_mut(ptr, len));
    }
}

// ── Tests ──────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::ptr;

    #[test]
    fn ffi_compress_roundtrip() {
        let json = br#"{"method":"ping","id":1}"#;

        let mut out: *mut u8 = ptr::null_mut();
        let mut out_len: usize = 0;

        assert_eq!(
            lumen_compress(json.as_ptr(), json.len(), &mut out, &mut out_len),
            0
        );
        assert!(!out.is_null());
        assert!(out_len > 0);

        // Decompress back
        let mut json_out: *mut u8 = ptr::null_mut();
        let mut json_len: usize = 0;

        assert_eq!(
            lumen_decompress(out, out_len, &mut json_out, &mut json_len),
            0
        );
        assert!(!json_out.is_null());
        assert!(json_len > 0);

        let decompressed =
            unsafe { std::slice::from_raw_parts(json_out, json_len) };
        let original: serde_json::Value = serde_json::from_slice(json).unwrap();
        let roundtripped: serde_json::Value =
            serde_json::from_slice(decompressed).unwrap();
        assert_eq!(original, roundtripped);

        // Clean up
        lumen_free(out, out_len);
        lumen_free(json_out, json_len);
    }

    #[test]
    fn ffi_invalid_json() {
        let json = b"not json";

        let mut out: *mut u8 = ptr::null_mut();
        let mut out_len: usize = 0;

        assert_eq!(
            lumen_compress(json.as_ptr(), json.len(), &mut out, &mut out_len),
            -1
        );
        assert!(out.is_null());
    }

    #[test]
    fn ffi_invalid_lumen() {
        let data = b"\xFF\xFF\xFF invalid";

        let mut out: *mut u8 = ptr::null_mut();
        let mut out_len: usize = 0;

        assert_eq!(
            lumen_decompress(data.as_ptr(), data.len(), &mut out, &mut out_len),
            -1
        );
        assert!(out.is_null());
    }

    #[test]
    fn ffi_null_pointer_safety() {
        let mut out: *mut u8 = ptr::null_mut();
        let mut out_len: usize = 0;

        // Null input — should not crash
        assert_eq!(
            lumen_compress(ptr::null(), 0, &mut out, &mut out_len),
            -1
        );
        assert_eq!(
            lumen_decompress(ptr::null(), 0, &mut out, &mut out_len),
            -1
        );
    }

    #[test]
    fn ffi_free_null_is_safe() {
        lumen_free(ptr::null_mut(), 0);
        lumen_free(ptr::null_mut(), 10); // mismatched len, should still not crash
    }

    #[test]
    fn ffi_version() {
        assert_eq!(lumen_version(), 0x0001_0000);
    }

    #[test]
    fn ffi_golden_binary_compat() {
        // Validate FFI compress matches Python golden files byte-for-byte.
        let golden_dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..").join("..").join("tests").join("e2e").join("golden");
        let vectors_path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("..").join("..").join("tests").join("e2e").join("shared_vectors.json");

        let raw = std::fs::read_to_string(&vectors_path).expect("shared_vectors.json not found");
        let data: serde_json::Value = serde_json::from_str(&raw).unwrap();
        let vectors = data["vectors"].as_array().unwrap();

        for v in vectors {
            let name = v["name"].as_str().unwrap();
            let golden_path = golden_dir.join(format!("{}.lumen", name));
            if !golden_path.exists() {
                continue;
            }

            let golden = std::fs::read(&golden_path)
                .unwrap_or_else(|_| panic!("Cannot read golden for {}", name));

            // Decompress golden to get original value
            let value = crate::compress::decompress(&golden)
                .unwrap_or_else(|| panic!("Cannot decompress golden for {}", name));

            // Re-serialize to JSON (what FFI expects)
            let json_str = serde_json::to_string(&value).unwrap();
            let json_bytes = json_str.as_bytes();

            // Compress via FFI
            let mut out: *mut u8 = ptr::null_mut();
            let mut out_len: usize = 0;

            let ret = lumen_compress(
                json_bytes.as_ptr(),
                json_bytes.len(),
                &mut out,
                &mut out_len,
            );
            assert_eq!(ret, 0, "FFI compress failed for {}", name);
            assert!(!out.is_null());
            assert!(out_len > 0);

            let ffi_bytes = unsafe { std::slice::from_raw_parts(out, out_len) };
            assert_eq!(
                ffi_bytes, golden.as_slice(),
                "FFI binary mismatch for \"{}\"", name
            );

            lumen_free(out, out_len);
        }
    }
}
