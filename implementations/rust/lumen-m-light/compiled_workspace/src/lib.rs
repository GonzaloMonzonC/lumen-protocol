use lumen_mlight::*;

#[no_mangle]
pub extern "C" fn compiled_routine(input: i64) -> i64 {
    let x = input as f64;
    (x + 1.0) as i64
}
