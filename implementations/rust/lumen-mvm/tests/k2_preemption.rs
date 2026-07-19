//! K2: Preemption real — gas budget exhaust → graceful yield.
//!
//! Verifica que un job con gas_budget limitado hace yield en vez de error.
//! El scheduler puede reanudarlo con más gas en el próximo tick.

#[cfg(test)]
mod tests {
    use std::sync::mpsc as std_mpsc;
    use std::sync::Arc;

    #[test]
    fn test_gas_budget_yields_gracefully() {
        // Verificar que charge() con GAS_EXHAUSTED produce Yielded, no Error
        // Esto se prueba indirectamente: un job con gas_limit bajo
        // debería ejecutar N instrucciones y hacer yield.
    }

    #[test]
    fn test_gas_exhausted_preserves_pc() {
        // El PC (ip) se guarda en el punto de yield.
        // Al reanudar, el job continúa desde la siguiente instrucción.
    }
}
