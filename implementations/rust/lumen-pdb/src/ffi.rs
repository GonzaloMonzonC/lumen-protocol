//! ffi.rs — C ABI para el engine redb (mismo patrón que el ffi.rs del
//! protocolo LUMEN). Consumido desde Python vía ctypes (lumen_pdb.py).
//!
//! Convenciones:
//!   - handle opaco *mut Pdb de lp_open / lp_close
//!   - buffers de salida: el callee aloca, el caller libera con lp_free
//!   - retornos: 0 = ok/encontrado, 1 = no encontrado/fin, <0 = error

use crate::globals::Pdb;
use std::ffi::CStr;
use std::os::raw::{c_char, c_double, c_int};
use std::slice;

unsafe fn cstr<'a>(p: *const c_char) -> Option<&'a str> {
    if p.is_null() {
        return None;
    }
    CStr::from_ptr(p).to_str().ok()
}

unsafe fn bytes<'a>(p: *const u8, len: usize) -> &'a [u8] {
    if p.is_null() || len == 0 {
        &[]
    } else {
        slice::from_raw_parts(p, len)
    }
}

unsafe fn out_buf(data: Vec<u8>, out: *mut *mut u8, out_len: *mut usize) -> bool {
    if out.is_null() || out_len.is_null() {
        return false;
    }
    let boxed = data.into_boxed_slice();
    let len = boxed.len();
    let ptr = Box::into_raw(boxed) as *mut u8;
    *out = ptr;
    *out_len = len;
    true
}

/// Abre una base redb y devuelve un handle opaco, o NULL si falla.
///
/// # Safety
///
/// `path` debe apuntar a una C-string válida durante toda la llamada.
#[no_mangle]
pub unsafe extern "C" fn lp_open(path: *const c_char) -> *mut Pdb {
    match cstr(path).and_then(|p| Pdb::open(p).ok()) {
        Some(db) => Box::into_raw(Box::new(db)),
        None => std::ptr::null_mut(),
    }
}

/// Cierra un handle creado por [`lp_open`].
///
/// # Safety
///
/// `h` debe venir de `lp_open`, no haberse cerrado antes y no reutilizarse.
#[no_mangle]
pub unsafe extern "C" fn lp_close(h: *mut Pdb) {
    if !h.is_null() {
        drop(Box::from_raw(h));
    }
}

/// Libera un buffer devuelto por esta ABI.
///
/// # Safety
///
/// `ptr` y `len` deben ser exactamente el par entregado por una función `lp_*`.
#[no_mangle]
pub unsafe extern "C" fn lp_free(ptr: *mut u8, len: usize) {
    if !ptr.is_null() {
        drop(Box::from_raw(std::ptr::slice_from_raw_parts_mut(ptr, len)));
    }
}

/// Escribe un valor raw.
///
/// # Safety
///
/// `h` debe ser válido; `ns` una C-string; `key` y `val` deben apuntar a
/// buffers legibles de las longitudes indicadas (o ser NULL si longitud 0).
#[no_mangle]
pub unsafe extern "C" fn lp_set(
    h: *mut Pdb,
    ns: *const c_char,
    key: *const u8,
    key_len: usize,
    val: *const u8,
    val_len: usize,
) -> c_int {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    match db.set(ns, bytes(key, key_len), bytes(val, val_len)) {
        Ok(()) => 0,
        Err(_) => -2,
    }
}

/// Bulk set: N pares empaquetados como `[len_k u32 LE][k][len_v u32 LE][v]...`.
///
/// # Safety
///
/// `h` y `ns` deben ser válidos; `buf` debe ser legible durante `buf_len` bytes.
#[no_mangle]
pub unsafe extern "C" fn lp_set_many(
    h: *mut Pdb,
    ns: *const c_char,
    buf: *const u8,
    buf_len: usize,
) -> i64 {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    let data = bytes(buf, buf_len);
    let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    let mut i = 0usize;
    while i + 4 <= data.len() {
        let kl = u32::from_le_bytes(data[i..i + 4].try_into().unwrap()) as usize;
        i += 4;
        if i + kl + 4 > data.len() {
            return -3;
        }
        let k = data[i..i + kl].to_vec();
        i += kl;
        let vl = u32::from_le_bytes(data[i..i + 4].try_into().unwrap()) as usize;
        i += 4;
        if i + vl > data.len() {
            return -3;
        }
        let v = data[i..i + vl].to_vec();
        i += vl;
        pairs.push((k, v));
    }
    if i != data.len() {
        return -3;
    }
    match db.set_many(ns, &pairs) {
        Ok(n) => n as i64,
        Err(_) => -2,
    }
}

/// Lee un valor raw y transfiere su buffer al caller.
///
/// # Safety
///
/// Además de un handle, namespace y clave válidos, `out` y `out_len` deben
/// ser punteros escribibles. El resultado debe liberarse con [`lp_free`].
#[no_mangle]
pub unsafe extern "C" fn lp_get(
    h: *mut Pdb,
    ns: *const c_char,
    key: *const u8,
    key_len: usize,
    out: *mut *mut u8,
    out_len: *mut usize,
) -> c_int {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    match db.get(ns, bytes(key, key_len)) {
        Ok(Some(v)) => {
            if out_buf(v, out, out_len) {
                0
            } else {
                -1
            }
        }
        Ok(None) => 1,
        Err(_) => -2,
    }
}

/// Borra el nodo y su subárbol.
///
/// # Safety
///
/// `h`, `ns` y el buffer `key` deben cumplir el contrato descrito en [`lp_set`].
#[no_mangle]
pub unsafe extern "C" fn lp_kill(
    h: *mut Pdb,
    ns: *const c_char,
    key: *const u8,
    key_len: usize,
) -> i64 {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    match db.kill(ns, bytes(key, key_len)) {
        Ok(n) => n as i64,
        Err(_) => -2,
    }
}

/// Implementa `$DATA` sobre una clave raw.
///
/// # Safety
///
/// `h`, `ns` y el buffer `key` deben cumplir el contrato descrito en [`lp_set`].
#[no_mangle]
pub unsafe extern "C" fn lp_data(
    h: *mut Pdb,
    ns: *const c_char,
    key: *const u8,
    key_len: usize,
) -> c_int {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    match db.data(ns, bytes(key, key_len)) {
        Ok(v) => v as c_int,
        Err(_) => -2,
    }
}

/// `current_seg_len == 0` busca desde el principio (`dir=1`) o final (`dir=-1`).
/// Devuelve 0 y el segmento codificado en out, o 1 si no hay más.
///
/// # Safety
///
/// Todos los buffers de entrada deben ser legibles para sus longitudes;
/// `out` y `out_len` deben ser escribibles. El resultado se libera con `lp_free`.
#[no_mangle]
pub unsafe extern "C" fn lp_order(
    h: *mut Pdb,
    ns: *const c_char,
    parent: *const u8,
    parent_len: usize,
    current_seg: *const u8,
    current_seg_len: usize,
    direction: c_int,
    out: *mut *mut u8,
    out_len: *mut usize,
) -> c_int {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    let cur = if current_seg_len == 0 {
        None
    } else {
        Some(bytes(current_seg, current_seg_len))
    };
    match db.order(ns, bytes(parent, parent_len), cur, direction) {
        Ok(Some(seg)) => {
            if out_buf(seg, out, out_len) {
                0
            } else {
                -1
            }
        }
        Ok(None) => 1,
        Err(_) => -2,
    }
}

/// Incrementa atómicamente un valor numérico.
///
/// # Safety
///
/// `h`, `ns` y `key` deben ser válidos; `out_new` debe ser escribible.
#[no_mangle]
pub unsafe extern "C" fn lp_incr(
    h: *mut Pdb,
    ns: *const c_char,
    key: *const u8,
    key_len: usize,
    delta: c_double,
    out_new: *mut c_double,
) -> c_int {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    if out_new.is_null() {
        return -1;
    }
    match db.incr(ns, bytes(key, key_len), delta) {
        Ok(v) => {
            *out_new = v;
            0
        }
        Err(_) => -2,
    }
}

/// Copia un nodo/subárbol reescribiendo el prefijo de sus claves.
///
/// # Safety
///
/// El handle, ambas C-strings y ambos buffers de clave deben ser válidos.
#[no_mangle]
pub unsafe extern "C" fn lp_merge(
    h: *mut Pdb,
    dst_ns: *const c_char,
    dst_key: *const u8,
    dst_key_len: usize,
    src_ns: *const c_char,
    src_key: *const u8,
    src_key_len: usize,
) -> i64 {
    let (Some(db), Some(dns), Some(sns)) = (h.as_ref(), cstr(dst_ns), cstr(src_ns)) else {
        return -1;
    };
    match db.merge(
        dns,
        bytes(dst_key, dst_key_len),
        sns,
        bytes(src_key, src_key_len),
    ) {
        Ok(n) => n as i64,
        Err(_) => -2,
    }
}

/// Cuenta las claves de un namespace.
///
/// # Safety
///
/// `h` debe ser un handle vivo y `ns` debe ser una C-string válida.
#[no_mangle]
pub unsafe extern "C" fn lp_count(h: *mut Pdb, ns: *const c_char) -> i64 {
    let (Some(db), Some(ns)) = (h.as_ref(), cstr(ns)) else {
        return -1;
    };
    match db.count(ns) {
        Ok(n) => n as i64,
        Err(_) => -2,
    }
}

/// Fuerza un commit duradero, usado al finalizar migraciones.
///
/// # Safety
///
/// `h` debe ser un handle vivo creado por [`lp_open`].
#[no_mangle]
pub unsafe extern "C" fn lp_flush(h: *mut Pdb) -> c_int {
    let Some(db) = h.as_ref() else { return -1 };
    match db.flush() {
        Ok(()) => 0,
        Err(_) => -2,
    }
}
