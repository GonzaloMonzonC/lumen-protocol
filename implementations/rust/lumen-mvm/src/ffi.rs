use crate::host::{CallbackBridge, HostCallback};
use crate::TokioMvm;
use serde_json::{json, Value as JsonValue};
use std::ffi::{c_char, c_void, CStr, CString};
use std::panic::{catch_unwind, AssertUnwindSafe};

fn owned(value: String) -> *mut c_char {
    CString::new(value)
        .unwrap_or_else(|_| CString::new(r#"{"success":false,"error":"embedded NUL"}"#).unwrap())
        .into_raw()
}

#[no_mangle]
/// Start a scheduler using a length-probed, response-cached JSON callback.
///
/// # Safety
/// The callback and context must remain valid until [`lmvm_free`].
pub unsafe extern "C" fn lmvm_new(
    callback: Option<HostCallback>,
    context: *mut c_void,
) -> *mut TokioMvm {
    let Some(callback) = callback else {
        return std::ptr::null_mut();
    };
    match catch_unwind(AssertUnwindSafe(|| {
        TokioMvm::start(CallbackBridge::new(callback, context))
    })) {
        Ok(Ok(runtime)) => Box::into_raw(Box::new(runtime)),
        _ => std::ptr::null_mut(),
    }
}

#[no_mangle]
/// Execute one JSON scheduler operation.
///
/// # Safety
/// `handle` must come from [`lmvm_new`] and `request` must be a valid,
/// NUL-terminated UTF-8 string.
pub unsafe extern "C" fn lmvm_call_json(
    handle: *mut TokioMvm,
    request: *const c_char,
) -> *mut c_char {
    if handle.is_null() || request.is_null() {
        return owned(json!({"success":false,"error":"null MVM handle/request"}).to_string());
    }
    let request = match CStr::from_ptr(request)
        .to_str()
        .ok()
        .and_then(|value| serde_json::from_str::<JsonValue>(value).ok())
    {
        Some(value) => value,
        None => return owned(json!({"success":false,"error":"invalid JSON request"}).to_string()),
    };
    let response = catch_unwind(AssertUnwindSafe(|| (&*handle).call(request)))
        .ok()
        .and_then(Result::ok)
        .unwrap_or_else(|| json!({"success":false,"error":"MVM scheduler call failed"}));
    owned(response.to_string())
}

#[no_mangle]
/// Stop and release a scheduler.
///
/// # Safety
/// `handle` must be null or an unreleased pointer returned by [`lmvm_new`].
pub unsafe extern "C" fn lmvm_free(handle: *mut TokioMvm) {
    if !handle.is_null() {
        drop(Box::from_raw(handle));
    }
}

#[no_mangle]
/// Release a string returned by [`lmvm_call_json`].
///
/// # Safety
/// `value` must be null or an unreleased string returned by this library.
pub unsafe extern "C" fn lmvm_string_free(value: *mut c_char) {
    if !value.is_null() {
        drop(CString::from_raw(value));
    }
}
