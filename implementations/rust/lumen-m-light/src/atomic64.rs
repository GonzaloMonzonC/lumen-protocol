//! Atómicos portátiles para el port a plataformas delgadas.
//!
//! `std::sync::atomic::AtomicU64` NO existe en targets sin atómicos de 64 bits
//! (p. ej. `mips*` 32-bit → error E0432 al compilar para routers MIPS).
//! `Atomic64` = el atómico real donde el target lo soporta; fallback con
//! `Mutex<u64>` donde no (contadores de jobs: uso ligero, coste despreciable).

#[cfg(target_has_atomic = "64")]
pub type Atomic64 = std::sync::atomic::AtomicU64;

#[cfg(not(target_has_atomic = "64"))]
#[derive(Debug)]
pub struct Atomic64(std::sync::Mutex<u64>);

#[cfg(not(target_has_atomic = "64"))]
impl Atomic64 {
    pub const fn new(v: u64) -> Self {
        Self(std::sync::Mutex::new(v))
    }

    pub fn load(&self, _o: std::sync::atomic::Ordering) -> u64 {
        *self.0.lock().unwrap()
    }

    pub fn store(&self, v: u64, _o: std::sync::atomic::Ordering) {
        *self.0.lock().unwrap() = v;
    }

    pub fn fetch_add(&self, v: u64, _o: std::sync::atomic::Ordering) -> u64 {
        let mut g = self.0.lock().unwrap();
        let old = *g;
        *g = old.wrapping_add(v);
        old
    }
}
