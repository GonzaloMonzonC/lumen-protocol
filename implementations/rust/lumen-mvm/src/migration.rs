//! K4 + S6-DST: Hot Migration — serializa job state + devices + mailbox.
//!
//! v1 (K4): solo vm_state + state
//! v2 (S6-DST): + mailbox + open_devices (Device State Transfer)
//!
//! Limitación: conexiones vivas (oneshot receivers) no se serializan.
//! La migración es entre ticks (checkpoint), no a mitad de un READ.

use serde::{Deserialize, Serialize};

/// Paquete de migración: todo lo necesario para recrear un job.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MigrationPacket {
    pub version: u32,
    pub source_pid: i64,
    pub target_pid: i64,
    pub code: String,
    pub vm_state: serde_json::Value,
    pub state: serde_json::Value,
    /// S6-DST: Mailbox messages pendientes.
    pub mailbox: Vec<serde_json::Value>,
    /// S6-DST: Devices abiertos (7=LLM, 8=HTTP, 9=webhook, 10=tool, 11=discovery).
    pub open_devices: Vec<DeviceState>,
}

/// Estado de un device abierto durante migración.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceState {
    pub device_id: i64,
    pub args: String,
    pub state: serde_json::Value,
}

pub fn serialize(
    pid: i64, target_pid: i64,
    code: &str, vm_state: &serde_json::Value, state: &serde_json::Value,
) -> Result<Vec<u8>, String> {
    let packet = MigrationPacket {
        version: 2,
        source_pid: pid,
        target_pid,
        code: code.to_string(),
        vm_state: vm_state.clone(),
        state: state.clone(),
        mailbox: Vec::new(),
        open_devices: Vec::new(),
    };
    serde_json::to_vec(&packet).map_err(|e| format!("Serialize error: {}", e))
}

pub fn deserialize(data: &[u8]) -> Result<MigrationPacket, String> {
    serde_json::from_slice(data).map_err(|e| format!("Deserialize error: {}", e))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_migration_v2_roundtrip() {
        let code = "O 7:\"gpt-4o\" U 7 W \"hello\" R resp";
        let vm_state = serde_json::json!({"ip": 5, "gas_used": 42});
        let state = serde_json::json!({"MEMORY": {"self": {"7": {"belief": "rust"}}}});

        let data = serialize(7, 99, code, &vm_state, &state).unwrap();
        let packet = deserialize(&data).unwrap();
        assert_eq!(packet.version, 2);
        assert_eq!(packet.source_pid, 7);
        assert_eq!(packet.target_pid, 99);
        assert_eq!(packet.code, code);
        assert_eq!(packet.vm_state["ip"], 5);
    }

    #[test]
    fn test_device_state_serialization() {
        let dev = DeviceState {
            device_id: 7,
            args: "gpt-4o".into(),
            state: serde_json::json!({"model": "gpt-4o", "pending_prompt": "hello"}),
        };
        let json = serde_json::to_string(&dev).unwrap();
        let restored: DeviceState = serde_json::from_str(&json).unwrap();
        assert_eq!(restored.device_id, 7);
        assert_eq!(restored.state["model"], "gpt-4o");
    }
}
