//! S2: PromptBuilder v0.2 — construye el prompt del LLM desde ^GLOBALS.
//!
//! Lee de ^MEMORY, ^MAILBOX, ^MODELS usando $ORDER con límites.
//! Secciones:
//! 1. System header  → "Eres Job N en LUMEN. Gas restante: Y."
//! 2. Mailbox        → Últimos 10 mensajes
//! 3. Memoria        → Últimas 20 entradas de ^MEMORY("self", pid)
//! 4. Modelo mental  → ^MODELS("active") a 1 nivel
//! 5. Estado         → gas_used
//! 6. Formato        → Instrucciones de salida (```m / ```tool / ```msg / texto)
//!
//! Constraints del spec v0.2: sin embeddings, límites estrictos, sin función
//! del modelo activo más allá de 1 nivel.

use lumen_mlight::{Host, Subscript};

pub struct PromptBuilder {
    pub pid: i64,
    pub gas_used: u64,
}

impl PromptBuilder {
    pub fn new(pid: i64, gas_used: u64) -> Self {
        Self { pid, gas_used }
    }

    /// Construye el prompt completo a partir del Host (acceso a ^GLOBALS).
    pub fn build<H: Host>(&self, host: &H) -> Result<(String, String), String> {
        let system = self.build_system(host)?;
        let user = self.build_user(host)?;
        Ok((system, user))
    }

    fn build_system<H: Host>(&self, host: &H) -> Result<String, String> {
        let mut s = String::new();
        s.push_str(&format!(
            "Eres el Job {} en LUMEN M-Light VM v1.\n\
             Gas usado: {}/{}. Trabajas con ^GLOBALS jerárquicas.\n\
             Tu tarea es pensar y decidir la próxima acción.\n\n",
            self.pid, self.gas_used, 5000
        ));

        // Modelo mental activo (1 nivel)
        s.push_str("## Modelo mental activo\n");
        let mut model_count = 0;
        let mut sub = String::new();
        loop {
            match host.order("MODELS", &[Subscript::String("active".into())], Some(&Subscript::String(sub.clone())), 1)? {
                Some(next) => {
                    if let Subscript::String(key) = &next {
                        let val = host.get("MODELS", &[
                            Subscript::String("active".into()),
                            Subscript::String(key.clone()),
                        ])?;
                        if let Some(v) = val {
                            s.push_str(&format!("- {}: {}\n", key, v.as_string()));
                            model_count += 1;
                        }
                        sub = key.clone();
                    } else {
                        break;
                    }
                }
                None => break,
            }
            if model_count >= 5 { break; }
        }
        if model_count == 0 {
            s.push_str("(vacío)\n");
        }

        // Instrucciones de formato de salida
        s.push_str("\n## Formato de respuesta\n\
            Responde en UNO de estos formatos:\n\
            - ```m\\n<código M>\\n``` → ejecutaré el código M en el próximo tick\n\
            - ```tool\\n{\"tool\":\"nombre\",\"args\":{...}}\\n``` → llamaré a una herramienta\n\
            - ```msg <destino>\\n<mensaje>\\n``` → enviaré mensaje a otro job\n\
            - Texto plano → guardaré en ^OUTPUT para el usuario\n");

        Ok(s)
    }

    fn build_user<H: Host>(&self, host: &H) -> Result<String, String> {
        let mut s = String::new();

        // Mailbox: últimos 10 mensajes
        s.push_str("## Bandeja de entrada\n");
        let mut mailbox_count = 0;
        let mut sub = String::new();
        loop {
            match host.order("MAILBOX", &[Subscript::Number(self.pid as f64)], Some(&Subscript::String(sub.clone())), 1)? {
                Some(next) => {
                    if let Subscript::String(msg_id) = &next {
                        let val = host.get("MAILBOX", &[
                            Subscript::Number(self.pid as f64),
                            Subscript::String(msg_id.clone()),
                        ])?;
                        if let Some(v) = val {
                            s.push_str(&format!("- {}: {}\n", msg_id, v.as_string()));
                            mailbox_count += 1;
                        }
                        sub = msg_id.clone();
                    } else {
                        break;
                    }
                }
                None => break,
            }
            if mailbox_count >= 10 { break; }
        }
        if mailbox_count == 0 {
            s.push_str("(sin mensajes)\n");
        }

        // Memoria: últimas 20 entradas
        s.push_str("\n## Memoria\n");
        let mut mem_count = 0;
        let mut mem_sub = String::new();
        let mem_ns = format!("MEMORY_{}", self.pid);
        loop {
            match host.order(&mem_ns, &[], Some(&Subscript::String(mem_sub.clone())), 1)? {
                Some(next) => {
                    if let Subscript::String(key) = &next {
                        let val = host.get(&mem_ns, &[Subscript::String(key.clone())])?;
                        if let Some(v) = val {
                            let v_str = v.as_string();
                            if v_str.len() > 200 {
                                s.push_str(&format!("- {}: {}...\n", key, &v_str[..200]));
                            } else {
                                s.push_str(&format!("- {}: {}\n", key, v_str));
                            }
                            mem_count += 1;
                        }
                        mem_sub = key.clone();
                    } else {
                        break;
                    }
                }
                None => break,
            }
            if mem_count >= 20 { break; }
        }
        if mem_count == 0 {
            s.push_str("(sin memoria)\n");
        }

        // Estado
        s.push_str(&format!("\n## Estado\n\
            Gas usado: {}/{}\n\
            PID: {}\n\
            ¿Qué acción tomas ahora?\n",
            self.gas_used, 5000, self.pid
        ));

        Ok(s)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lumen_mlight::Value;
    use std::collections::HashMap;

    /// Mock host para tests del PromptBuilder.
    struct MockHost {
        data: HashMap<String, String>,
    }

    impl MockHost {
        fn new() -> Self { Self { data: HashMap::new() } }

        fn insert(&mut self, key: &str, val: &str) {
            self.data.insert(key.to_string(), val.to_string());
        }
    }

    impl Host for MockHost {
        fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
            let key = format!("{}|{:?}", ns, subs);
            Ok(self.data.get(&key).map(|v| Value::String(v.clone())))
        }
        fn set(&mut self, _ns: &str, _subs: &[Subscript], _value: Value) -> Result<(), String> { Ok(()) }
        fn kill(&mut self, _ns: &str, _subs: &[Subscript]) -> Result<u64, String> { Ok(0) }
        fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
            let key = format!("{}|{:?}", ns, subs);
            Ok(if self.data.contains_key(&key) { 1 } else { 0 })
        }
        fn order(&self, _ns: &str, _parent: &[Subscript], current: Option<&Subscript>, _direction: i32) -> Result<Option<Subscript>, String> {
            // Simple mock: if current is "", return first key; otherwise None
            if let Some(c) = current {
                if let Subscript::String(s) = c {
                    if s.is_empty() {
                        // Return first key that matches parent
                        for (k, _) in &self.data {
                            if k.starts_with("MEMORY_7|") {
                                let parts: Vec<&str> = k.split('|').collect();
                                if parts.len() >= 2 {
                                    return Ok(Some(Subscript::String(parts[1].trim_matches(&['[', '"', ']'] as &[_]).to_string())));
                                }
                            }
                        }
                    }
                }
            }
            Ok(None)
        }
        fn transaction_start(&mut self) -> Result<(), String> { Ok(()) }
        fn transaction_commit(&mut self) -> Result<(), String> { Ok(()) }
        fn transaction_rollback(&mut self) -> Result<(), String> { Ok(()) }
        fn transaction_level(&self) -> usize { 0 }
        fn routine(&self, _name: &str) -> Result<Option<String>, String> { Ok(None) }
        fn read(&mut self) -> Result<String, String> { Ok(String::new()) }
        fn read_would_block(&self) -> bool { false }
        fn lock(&mut self, _ns: &str, _subs: &[Subscript], _timeout: Option<f64>) -> Result<bool, String> { Ok(true) }
        fn unlock(&mut self, _ns: &str, _subs: &[Subscript]) -> Result<(), String> { Ok(()) }
        fn unlock_all(&mut self) -> Result<(), String> { Ok(()) }
    }

    #[test]
    fn test_prompt_builder_empty() {
        let host = MockHost::new();
        let builder = PromptBuilder::new(7, 42);
        let (system, user) = builder.build(&host).unwrap();
        assert!(system.contains("Job 7"));
        assert!(system.contains("Gas usado: 42"));
        assert!(user.contains("sin memoria"));
        assert!(user.contains("sin mensajes"));
    }

    #[test]
    fn test_prompt_builder_format_instructions() {
        let host = MockHost::new();
        let builder = PromptBuilder::new(1, 0);
        let (_system, _user) = builder.build(&host).unwrap();
        assert!(_system.contains("```m"));
        assert!(_system.contains("```tool"));
        assert!(_system.contains("```msg"));
    }
}
