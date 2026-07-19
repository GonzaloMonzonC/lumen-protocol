//! K4: Hot Migration — serializa job state, transporta, rehidrata.
//!
//! MVP: JSON serialization + mpsc channel transport.
//! QUIC L4 (quic.rs) se puede conectar como backend de transporte.
//!
//! Flujo:
//!   source_node: pdb_mvm_migrate(pid) → serialize → send
//!   target_node: pdb_mvm_receive(data) → deserialize → spawn

use serde::{Deserialize, Serialize};

/// Paquete de migración: todo lo necesario para recrear un job.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MigrationPacket {
    /// Versión del protocolo de migración.
    pub version: u32,
    /// PID del job origen.
    pub source_pid: i64,
    /// PID asignado en destino.
    pub target_pid: i64,
    /// Código fuente M del job.
    pub code: String,
    /// Estado de la VM serializado (VmState JSON).
    pub vm_state: serde_json::Value,
    /// ^STATE(pid, *) — copia completa del namespace.
    pub state: serde_json::Value,
    /// Timestamp de migración.
    pub migrated_at: String,
}

/// Serializa un job para migración.
pub fn serialize(
    pid: i64,
    target_pid: i64,
    code: &str,
    vm_state: &serde_json::Value,
    state: &serde_json::Value,
) -> Result<Vec<u8>, String> {
    let packet = MigrationPacket {
        version: 1,
        source_pid: pid,
        target_pid,
        code: code.to_string(),
        vm_state: vm_state.clone(),
        state: state.clone(),
        migrated_at: String::new(), // filled by sender node
    };
    serde_json::to_vec(&packet).map_err(|e| format!("Serialize error: {}", e))
}

/// Deserializa un paquete de migración.
pub fn deserialize(data: &[u8]) -> Result<MigrationPacket, String> {
    serde_json::from_slice(data).map_err(|e| format!("Deserialize error: {}", e))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_migration_roundtrip() {
        let code = "S ^X=42 W \"hello\"";
        let vm_state = serde_json::json!({"ip": 0, "gas_used": 10});
        let state = serde_json::json!({"MEMORY": {"self": {"7": {"belief": "rust"}}}});

        let data = serialize(7, 99, code, &vm_state, &state).unwrap();
        assert!(!data.is_empty());

        let packet = deserialize(&data).unwrap();
        assert_eq!(packet.version, 1);
        assert_eq!(packet.source_pid, 7);
        assert_eq!(packet.target_pid, 99);
        assert_eq!(packet.code, code);
        assert_eq!(packet.vm_state["ip"], 0);
    }
}
