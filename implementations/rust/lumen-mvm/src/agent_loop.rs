//! S4: Agent loop — código M canónico del agente persistente.
//!
//! El agente es un Job M normal con PID, gas, mailbox.
//! No hay modo especial del scheduler.
//!
//! Loop:
//!   CHECK_MAILBOX → THINK → YIELD → CHECK_MAILBOX → ...
//!
//! THINK_INTERNAL es un hook del Host (no una rutina M real).
//! El LlmHost intercepta y dispara la inferencia.
//!
//! Este módulo proporciona el código fuente M del agente.

/// Código fuente M del agente persistente.
/// Compila con `Compiler::compile()` y se spawnea como Job normal.
pub const AGENT_CODE: &str = r#"
AGENT
  ; ── Agente persistente LUMEN ──
  ; Ciclo: CHECK_MAILBOX → THINK → YIELD
  D CHECK_MAILBOX
  F {
    D THINK
    I $TEST Q  ; $TEST=1 → HALT
  }
  Q

CHECK_MAILBOX
  ; Leer mailbox y cargar en ^MEMORY para el próximo THINK
  S N=""
  F  S N=$O(^MAILBOX($J,N)) Q:N=""  D
  . S MSG=$G(^MAILBOX($J,N))
  . S ^MEMORY("self",$J,"last_msg")=MSG
  . KILL ^MAILBOX($J,N)  ; consumir mensaje
  Q

THINK
  ; Hook interceptado por LlmHost — no es una rutina real
  ; El Host detecta THINK_INTERNAL y dispara:
  ;   PromptBuilder → HTTP → ResponseParser → ^MEMORY/^OUTPUT/^MAILBOX
  S RESULT=$$THINK_INTERNAL()
  I RESULT="YIELD" Q
  I RESULT="HALT"  S $TEST=1 Q
  Q
"#;

#[cfg(test)]
mod tests {
    use lumen_mlight::Compiler;

    #[test]
    fn test_agent_code_compiles() {
        let program = Compiler::compile(super::AGENT_CODE);
        assert!(program.is_ok(), "Agent code should compile: {:?}", program.err());
        let p = program.unwrap();
        // AGENT es la unica label explicita; CHECK_MAILBOX/THINK son DO targets
        assert!(p.labels.contains_key("AGENT"));
    }

    #[test]
    fn test_agent_code_has_think_call() {
        let code = super::AGENT_CODE;
        // THINK_INTERNAL aparece como function call $$THINK_INTERNAL()
        assert!(code.contains("THINK_INTERNAL"));
        assert!(code.contains("CHECK_MAILBOX"));
    }
}
