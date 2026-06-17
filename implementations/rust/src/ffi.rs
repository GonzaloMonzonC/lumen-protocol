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
use std::cell::RefCell;

use crate::compress;

// ── Last-error storage (thread-local) ──────────────────────────────────────

thread_local! {
    static LAST_ERROR: RefCell<Option<String>> = const { RefCell::new(None) };
}

fn set_error(msg: String) {
    let truncated = if msg.len() > 512 { msg[..512].to_string() } else { msg };
    LAST_ERROR.with(|e| *e.borrow_mut() = Some(truncated));
}

fn take_error() -> Option<String> {
    LAST_ERROR.with(|e| e.borrow_mut().take())
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

    let compressed = compress::compress(&value, None);

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

    let value = match compress::decompress(data, None) {
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

// ── Level 2: Zero-Copy Shared Memory FFI ────────────────────────────────────

use crate::shm::{RingSide, ShmRegion};

/// Opaque handle to a shared memory region with two ring buffers.
///
/// Created by `lumen_shm_create` (server) or `lumen_shm_open` (client).
/// Freed by `lumen_shm_close`.
pub struct ShmOpaque {
    region: ShmRegion,
}

/// Create a new named shared memory region (server side).
///
/// - `name_ptr`, `name_len`: UTF-8 name for the region
///   (e.g. "/lumen-shm-1234-5678").
/// - `size`: region size in bytes (use 0 for default 512 KiB).
///
/// Returns a heap-allocated opaque handle on success, NULL on error
/// (call `lumen_error_message()`). The caller MUST free with
/// `lumen_shm_close`.
///
/// The header is initialised with magic, version, and zeroed cursors.
#[no_mangle]
pub extern "C" fn lumen_shm_create(
    name_ptr: *const u8,
    name_len: u32,
    size: u32,
) -> *mut ShmOpaque {
    if name_ptr.is_null() || name_len == 0 {
        set_error("lumen_shm_create: null or empty name".into());
        return std::ptr::null_mut();
    }
    let name_bytes = unsafe { std::slice::from_raw_parts(name_ptr, name_len as usize) };
    let name = match std::str::from_utf8(name_bytes) {
        Ok(s) => s,
        Err(e) => {
            set_error(format!("lumen_shm_create: invalid UTF-8 name: {e}"));
            return std::ptr::null_mut();
        }
    };
    let sz = if size == 0 { 524288 } else { size as usize };

    match ShmRegion::create(Some(name), Some(sz)) {
        Ok(region) => {
            region.init_header();
            let handle = Box::new(ShmOpaque { region });
            Box::into_raw(handle)
        }
        Err(e) => {
            set_error(format!("lumen_shm_create: {e}"));
            std::ptr::null_mut()
        }
    }
}

/// Open an existing shared memory region by name (client side).
///
/// - `name_ptr`, `name_len`: UTF-8 name (must match `lumen_shm_create`).
/// - `size`: region size in bytes (use 0 for default 512 KiB).
///
/// Returns an opaque handle on success, NULL on error.
/// Caller MUST free with `lumen_shm_close`.
///
/// Validates that the region's magic and version match LUMEN.
#[no_mangle]
pub extern "C" fn lumen_shm_open(
    name_ptr: *const u8,
    name_len: u32,
    size: u32,
) -> *mut ShmOpaque {
    if name_ptr.is_null() || name_len == 0 {
        set_error("lumen_shm_open: null or empty name".into());
        return std::ptr::null_mut();
    }
    let name_bytes = unsafe { std::slice::from_raw_parts(name_ptr, name_len as usize) };
    let name = match std::str::from_utf8(name_bytes) {
        Ok(s) => s,
        Err(e) => {
            set_error(format!("lumen_shm_open: invalid UTF-8 name: {e}"));
            return std::ptr::null_mut();
        }
    };
    let sz = if size == 0 { 524288 } else { size as usize };

    match ShmRegion::open(name, Some(sz)) {
        Ok(region) => {
            if !region.validate() {
                set_error("lumen_shm_open: invalid magic or version — region not initialised".into());
                return std::ptr::null_mut();
            }
            let handle = Box::new(ShmOpaque { region });
            Box::into_raw(handle)
        }
        Err(e) => {
            set_error(format!("lumen_shm_open: {e}"));
            std::ptr::null_mut()
        }
    }
}

/// Write a length-prefixed frame into the ring buffer.
///
/// - `handle`: opaque handle from `lumen_shm_create` or `lumen_shm_open`.
/// - `side`: 0 = Ring A (Client→Server), 1 = Ring B (Server→Client).
/// - `data_ptr`, `data_len`: payload to write.
///
/// Returns 0 on success, -1 on error (call `lumen_error_message()` for details).
/// A timeout (peer dead) also returns -1 with an error message.
#[no_mangle]
pub extern "C" fn lumen_shm_write_frame(
    handle: *mut ShmOpaque,
    side: u8,
    data_ptr: *const u8,
    data_len: u32,
) -> i32 {
    if handle.is_null() || (data_ptr.is_null() && data_len > 0) {
        return -1;
    }
    let h = unsafe { &*handle };
    let rs = if side == 0 { RingSide::A } else { RingSide::B };
    let data = unsafe { std::slice::from_raw_parts(data_ptr, data_len as usize) };

    let ring = h.region.ring_buffer(rs);
    match ring.write_frame(data) {
        Ok(()) => 0,
        Err(e) => {
            set_error(format!("lumen_shm_write_frame: {e}"));
            -1
        }
    }
}

/// Read a length-prefixed frame from the ring buffer.
///
/// - `handle`: opaque handle.
/// - `side`: 0 = Ring A (Server reads), 1 = Ring B (Client reads).
///   (note: read side is opposite from write side — server reads A, client reads B)
/// - `buf_ptr`: caller-provided buffer to write the frame payload into.
/// - `buf_cap`: capacity of the caller's buffer in bytes.
/// - `out_len`: receives the actual payload length written.
///
/// Returns 0 on success, -1 if no complete frame is available.
/// If the frame is larger than `buf_cap`, returns -1 and sets error.
#[no_mangle]
pub extern "C" fn lumen_shm_read_frame(
    handle: *mut ShmOpaque,
    side: u8,
    buf_ptr: *mut u8,
    buf_cap: u32,
    out_len: *mut u32,
) -> i32 {
    if handle.is_null() || buf_ptr.is_null() || out_len.is_null() {
        return -1;
    }
    let h = unsafe { &*handle };
    let rs = if side == 0 { RingSide::A } else { RingSide::B };

    let ring = h.region.ring_buffer(rs);
    let mut frame = Vec::new();
    match ring.read_frame(&mut frame) {
        Ok(flen) => {
            if flen > buf_cap as usize {
                set_error(format!(
                    "lumen_shm_read_frame: frame length {} exceeds buffer capacity {}",
                    flen, buf_cap
                ));
                // Drain the frame so we don't get stuck on it
                return -1;
            }
            unsafe {
                std::ptr::copy_nonoverlapping(frame.as_ptr(), buf_ptr, flen);
                *out_len = flen as u32;
            }
            0
        }
        Err(e) => {
            set_error(format!("lumen_shm_read_frame: {e}"));
            -1
        }
    }
}

/// Close and free a shared memory handle.
///
/// Safe to call with NULL (no-op).  After this call the handle must
/// not be used.
#[no_mangle]
pub extern "C" fn lumen_shm_close(handle: *mut ShmOpaque) {
    if handle.is_null() {
        return;
    }
    unsafe {
        let _ = Box::from_raw(handle);
        // ShmRegion::drop unmaps and cleans up
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
            let value = crate::compress::decompress(&golden, None)
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
