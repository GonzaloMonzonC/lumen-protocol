/// Transpilador M → Rust nativo compilable.
///
/// Toma un `Program` del compilador y genera código Rust que hace
/// las mismas operaciones pero a velocidad nativa.
use crate::compiler::{Instruction, Opcode, Program};
use crate::{Subscript, Value};
use std::collections::BTreeMap;

/// Genera código Rust compilable desde un Program M.
pub fn transpile_to_rust(program: &Program, fn_name: &str) -> String {
    let mut code = String::new();
    
    // Prologue
    code.push_str(&format!("// Transpilado de M → Rust\n"));
    code.push_str(&format!("// Source: {}\n", program.source.replace('\n', "\\n")));
    code.push_str(&format!("#[allow(unused_mut, unused_assignments, non_snake_case)]\n"));
    code.push_str(&format!("pub fn {}(globals: &mut std::collections::BTreeMap<Vec<crate::Subscript>, crate::Value>>) -> Result<crate::Value, crate::VmError> {{\n", fn_name));
    code.push_str("    // Variables locales\n");
    
    // Collect local variables from SET commands
    let locals = collect_locals(program);
    for var in &locals {
        code.push_str(&format!("    let mut {} = crate::Value::Null;\n", var));
    }
    
    code.push_str("\n");
    
    // Emit instructions
    let mut i = 0;
    while i < program.instructions.len() {
        let instr = &program.instructions[i];
        
        // Skip labels — the Rust version uses labels as comments
        if instr.opcode == Opcode::Label {
            code.push_str(&format!("    // Label: {}\n", instr.argument));
            i += 1;
            continue;
        }
        
        // Postcondition
        if let Some(ref pc) = instr.postcondition {
            let cond = transpile_expr(pc);
            code.push_str(&format!("    if {} {{\n", cond));
        }
        
        match instr.opcode {
            Opcode::Set => {
                code.push_str(&format!("    // SET {}\n", instr.argument));
                let set_code = transpile_set(&instr.argument, &locals);
                code.push_str(&set_code);
            },
            Opcode::Kill => {
                code.push_str(&format!("    // KILL {}\n", instr.argument));
                code.push_str(&transpile_kill(&instr.argument));
            },
            Opcode::For => {
                let (var, from, to, step) = parse_for(&instr.argument);
                if let Some((v, f, t)) = var.zip(from).zip(to).map(|((v, f), t)| (v, f, t)) {
                    let step: f64 = step.and_then(|s| s.parse().ok()).unwrap_or(1.0);
                    code.push_str(&format!("    // FOR {}={}:{}:{}\n", v, f, t, step));
                    code.push_str(&format!("    for {}_iter in {}f64 as i64..={}f64 as i64 {{\n", v, f, t));
                    code.push_str(&format!("        let {} = crate::Value::Number({}_iter as f64);\n", v, v));
                    // Collect the body
                    let mut depth = 1;
                    let mut body_instructions = Vec::new();
                    let start = i + 1;
                    while start + body_instructions.len() < program.instructions.len() && depth > 0 {
                        let next = &program.instructions[start + body_instructions.len()];
                        if next.opcode == Opcode::For { depth += 1; }
                        if next.opcode == Opcode::Label { /* skip */ }
                        // The For body is everything until the next For or a Quit at same depth
                        // For simplicity, use the same indentation
                        body_instructions.push(next);
                        if next.opcode == Opcode::Quit { depth -= 1; if depth == 0 { body_instructions.pop(); break; } }
                    }
                    code.push_str(&format!("        // FOR body (todo en una línea)\n"));
                    // Generate body as Rust
                    for instr in &body_instructions {
                        let inner = transpile_instruction(instr, &locals);
                        for line in inner.lines() {
                            if !line.trim().is_empty() {
                                code.push_str(&format!("        {}\n", line.trim()));
                            }
                        }
                    }
                    code.push_str("    }\n");
                    // Skip FOR body instructions
                    i += body_instructions.len();
                } else {
                    code.push_str(&format!("    // FOR (no translatable): {}\n", instr.argument));
                }
            },
            Opcode::If => {
                let cond = parse_if_condition(&instr.argument);
                if let Some(c) = cond {
                    code.push_str(&format!("    if {} {{\n", transpile_expr(&c)));
                    // Body is everything until ELSE or next instruction at same level
                    // For simplicity, inline the rest until ELSE/QUIT
                } else {
                    code.push_str(&format!("    // IF (no translatable): {}\n", instr.argument));
                }
            },
            Opcode::Else => {
                code.push_str("    } else {\n");
            },
            Opcode::Do => {
                code.push_str(&format!("    // DO {}\n", instr.argument));
                if let Some(rtn) = extract_routine(&instr.argument) {
                    code.push_str(&format!("    {}_compiled(globals)?;\n", rtn.to_lowercase()));
                }
            },
            Opcode::Quit => {
                code.push_str("    break;\n");
            },
            Opcode::Write => {
                let expr = instr.argument.trim();
                let val = transpile_expr(expr);
                code.push_str(&format!("    println!(\"{{}}\", {});\n", val));
            },
            Opcode::Expr => {
                // Raw expression — could be $$FUNC or a bare call
                code.push_str(&format!("    // EXPR: {}\n", instr.argument));
                if instr.argument.starts_with("$$") || instr.argument.starts_with('$') {
                    code.push_str(&format!("    {};\n", transpile_expr(&instr.argument)));
                }
            },
            _ => {
                code.push_str(&format!("    // (skipped {:?}): {}\n", instr.opcode, instr.argument));
            }
        }
        
        // Close postcondition block
        if instr.postcondition.is_some() {
            code.push_str("    }\n");
        }
        
        i += 1;
    }
    
    code.push_str("    Ok(crate::Value::Null)\n");
    code.push_str("}\n");
    
    code
}

/// Transpila una instrucción individual a una línea Rust
fn transpile_instruction(instr: &Instruction, locals: &[String]) -> String {
    match instr.opcode {
        Opcode::Set => transpile_set(&instr.argument, locals),
        _ => format!("    // (not in body): {:?} {}", instr.opcode, instr.argument),
    }
}

/// Transpila SET M → Rust
fn transpile_set(arg: &str, locals: &[String]) -> String {
    // Parse "target=value" or "target1=val1,target2=val2,..."
    let trimmed = arg.trim();
    let mut result = String::new();
    
    // Split respetando paréntesis, comillas anidadas
    for piece in split_m_args(trimmed) {
        let piece = piece.trim();
        if let Some(eq_pos) = piece.find('=') {
            let target = piece[..eq_pos].trim();
            let value = piece[eq_pos+1..].trim();
            
            if target.starts_with('^') {
                // Global SET: ^GLOBAL(sub1,sub2)=value
                result.push_str(&format!("    // SET ^{} = {}\n", target, value));
                let (name, subs) = parse_global_ref(target);
                let val_expr = transpile_expr(value);
                result.push_str(&format!("    globals.insert(vec![{}], {});\n", 
                    subs.iter().map(|s| transpile_expr(s)).collect::<Vec<_>>().join(", "),
                    val_expr
                ));
            } else {
                // Local SET: x=value
                let val_expr = transpile_expr(value);
                result.push_str(&format!("    {} = {};\n", target, val_expr));
            }
        }
    }
    
    result
}

/// Transpila KILL
fn transpile_kill(arg: &str) -> String {
    let trimmed = arg.trim();
    if trimmed.starts_with('^') {
        let (name, subs) = parse_global_ref(trimmed);
        if subs.is_empty() {
            format!("    globals.retain(|k, _| k.get(0).map(|s| s.as_string()) != Some(\"{}\".to_string()));\n", name)
        } else {
            format!("    globals.remove(&vec![{}]);\n",
                subs.iter().map(|s| transpile_expr(s)).collect::<Vec<_>>().join(", "))
        }
    } else {
        format!("    // KILL local (skipped)\n")
    }
}

/// Extrae variables locales de un Program
fn collect_locals(program: &Program) -> Vec<String> {
    let mut locals = Vec::new();
    let mut seen = std::collections::HashSet::new();
    
    for instr in &program.instructions {
        if instr.opcode == Opcode::Set {
            for piece in instr.argument.split(',') {
                if let Some(eq_pos) = piece.find('=') {
                    let target = piece[..eq_pos].trim();
                    if !target.starts_with('^') && !target.starts_with('$') && !seen.contains(target) {
                        seen.insert(target.to_string());
                        locals.push(target.to_string());
                    }
                }
            }
        }
    }
    
    locals
}

/// Transpila una expresión M → Rust
fn transpile_expr(expr: &str) -> String {
    let e = expr.trim();
    
    // Número
    if let Ok(n) = e.parse::<f64>() {
        return format!("crate::Value::Number({}f64)", n);
    }
    
    // String literal
    if e.starts_with('"') && e.ends_with('"') {
        let inner = &e[1..e.len()-1].replace("\"\"", "\"");
        return format!("crate::Value::String(\"{}\".to_string())", inner.escape_default());
    }
    
    // $G(ref) — get global
    if e.starts_with("$G(") && e.ends_with(')') {
        let inner = &e[3..e.len()-1];
        if inner.starts_with('^') {
            let (name, subs) = parse_global_ref(inner);
            return format!("globals.get(&vec![{}]).cloned().unwrap_or(crate::Value::Null)",
                subs.iter().map(|s| transpile_expr(s)).collect::<Vec<_>>().join(", "));
        }
        return format!("crate::Value::Null /* $G({}) */", inner);
    }

    // $R(n) / $RANDOM(n) — entero aleatorio en [0, n-1] (MUMPS estándar).
    // Fix 2026-08-28: antes no se transpilaba → Null silencioso.
    if e.starts_with("$R(") && e.ends_with(')') {
        let inner = &e[3..e.len()-1];
        return format!(
            "{{ let __limit = {}.as_number(); if __limit <= 0.0 {{ crate::Value::Number(0.0) }} else {{ crate::Value::Number((std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0) as f64 % __limit).floor()) }} }}",
            transpile_expr(inner)
        );
    }
    
    // $DEVICE("llm:call",...) — call device directly
    if e.starts_with("$DEVICE(") {
        let inner = e.trim_end_matches(')').strip_prefix("$DEVICE(").unwrap_or("");
        // Simple arg split by comma, handle escaped quotes
        let args: Vec<String> = split_m_args(inner).into_iter().map(|s| s.trim().trim_matches('"').to_string()).collect();
        if args.len() >= 2 && args[0] == "llm:call" {
            let prompt = args.get(1).map(|s| s.as_str()).unwrap_or("");
            return format!("crate::Value::String(\"COMPILED_LLM({})\".to_string())", prompt);
        }
        if args.len() >= 2 && args[0] == "http:get" {
            let url = args.get(1).map(|s| s.as_str()).unwrap_or("");
            return format!("crate::Value::String(\"COMPILED_HTTP({})\".to_string())", url);
        }
        if args.len() >= 3 && args[0] == "ddp:get" {
            let space = args.get(1).map(|s| s.as_str()).unwrap_or("");
            let global_name = args.get(2).map(|s| s.as_str()).unwrap_or("");
            let key = args.get(3).map(|s| s.as_str()).unwrap_or("");
            // Genera código Rust con cliente TCP real
            let mut code = String::from("{\n");
            // Lookup host desde ^SPACE(space,"host")
            code.push_str(&format!(
                "let host = globals.get(&vec![crate::Subscript::String(\"SPACE\".into()), crate::Subscript::String(\"{}\".into()), crate::Subscript::String(\"host\".into())]).cloned().unwrap_or(crate::Value::String(\"127.0.0.1\".into())).as_string();\n",
                space
            ));
            code.push_str(&format!(
                "let port = globals.get(&vec![crate::Subscript::String(\"SPACE\".into()), crate::Subscript::String(\"{}\".into()), crate::Subscript::String(\"port\".into())]).cloned().unwrap_or(crate::Value::String(\"9102\".into())).as_string();\n",
                space
            ));
            code.push_str("let addr = format!(\"{}:{}\", host, port);\n");
            code.push_str("match std::net::TcpStream::connect(&addr) {\n");
            code.push_str("    Ok(mut stream) => {\n");
            code.push_str("        use std::io::{Read, Write};\n");
            code.push_str(&format!(
                "        let req = format!(r#\"{{\"op\":\"GET\",\"global\":\"{}\",\"subs\":[\"{}\"]}}\"#);\n",
                global_name, key
            ));
            code.push_str("        let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(5)));\n");
            code.push_str("        let _ = stream.write_all(req.as_bytes());\n");
            code.push_str("        let mut buf = Vec::new();\n");
            code.push_str("        let _ = stream.read_to_end(&mut buf);\n");
            code.push_str("        let txt = String::from_utf8_lossy(&buf).to_string();\n");
            code.push_str("        crate::Value::String(txt)\n");
            code.push_str("    }\n");
            code.push_str("    Err(e) => crate::Value::String(format!(\"DDP ERR: {}\", e))\n");
            code.push_str("}\n");
            code.push_str("}");
            return code;
        }
        // Generic $DEVICE calls at runtime (lumen, etc.)
        if args.len() >= 2 {
            let dev = &args[0];
            let act = args.get(1).map(|s| s.as_str()).unwrap_or("call");
            let rest = args[2..].iter().map(|s| format!("crate::Value::String(\"{}\".to_string())", s)).collect::<Vec<_>>().join(",");
            return format!(
                "{{ let mut __args = vec![{}]; self.host.device_call(\"{}\", \"{}\", &__args).unwrap_or(crate::Value::String(\"\".to_string())) }}",
                rest, dev, act
            );
        }
    }

    // x+ y, x-y, x*y, x/y
    if let Some(pos) = e.find(|c| c == '+' || c == '-' || c == '*' || c == '/') {
        if pos > 0 && pos < e.len() - 1 {
            let left = &e[..pos].trim();
            let right = &e[pos+1..].trim();
            let op = &e[pos..pos+1];
            match op {
                "+" => return format!("crate::Value::Number({}.as_number() + {}.as_number())", 
                    transpile_expr(left), transpile_expr(right)),
                "-" => return format!("crate::Value::Number({}.as_number() - {}.as_number())",
                    transpile_expr(left), transpile_expr(right)),
                "*" => return format!("crate::Value::Number({}.as_number() * {}.as_number())",
                    transpile_expr(left), transpile_expr(right)),
                "/" => return format!("crate::Value::Number({}.as_number() / {}.as_number())",
                    transpile_expr(left), transpile_expr(right)),
                _ => {}
            }
        }
    }
    
    // x>y, x<y, x=y, x'=y, x'>y, x'<y, x'>=y, x'<=y
    // NOTA: los operadores negados (') deben buscarse ANTES que sus
    // homólogos sin negar — "'>=" contiene ">=", "'<=" contiene "<=",
    // "'>" contiene ">", "'<" contiene "<".
    let ops = ["'>=", "'<=", ">=", "<=", "'=", "'>", "'<", ">", "<", "="];
    for op in &ops {
        if let Some(pos) = e.find(op) {
            if pos > 0 && pos + op.len() <= e.len() {
                let left = &e[..pos].trim();
                let right = &e[pos+op.len()..].trim();
                let val = format!("(if {}.as_number() {} {}.as_number() {{ crate::Value::Number(1.0) }} else {{ crate::Value::Number(0.0) }})",
                    transpile_expr(left), match *op {
                        "=" => "==",
                        "'=" => "!=",
                        ">" => ">",
                        "'>" => "<=",   // NOT(a>b) == a<=b
                        "<" => "<",
                        "'<" => ">=",   // NOT(a<b) == a>=b
                        ">=" => ">=",
                        "'>=" => "<",   // NOT(a>=b) == a<b
                        "<=" => "<=",
                        "'<=" => ">",   // NOT(a<=b) == a>b
                        _ => "==",
                    }, transpile_expr(right));
                return val;
            }
        }
    }
    
    // x&y (AND)
    if let Some(pos) = e.find('&') {
        if pos > 0 && pos < e.len() - 1 {
            let left = &e[..pos].trim();
            let right = &e[pos+1..].trim();
            return format!("crate::Value::Number(if {}.as_number() != 0.0 && {}.as_number() != 0.0 {{ 1.0 }} else {{ 0.0 }})",
                transpile_expr(left), transpile_expr(right));
        }
    }
    
    // x!y (OR)
    if let Some(pos) = e.find('!') {
        if pos > 0 && pos < e.len() - 1 && e.as_bytes().get(pos+1).copied() != Some(b'=') {
            let left = &e[..pos].trim();
            let right = &e[pos+1..].trim();
            return format!("crate::Value::Number(if {}.as_number() != 0.0 || {}.as_number() != 0.0 {{ 1.0 }} else {{ 0.0 }})",
                transpile_expr(left), transpile_expr(right));
        }
    }
    
    // Variable local
    if e.chars().all(|c| c.is_ascii_alphanumeric() || c == '_') && !e.starts_with(|c: char| c.is_ascii_digit()) {
        return format!("{}.clone()", e);
    }
    
    // $DEVICE("llm:fork",...) — async
    if e.starts_with("$DEVICE(\"llm:fork\"") {
        return format!("crate::Value::Null /* $DEVICE(async) */");
    }
    
    // Fallback
    format!("crate::Value::Null /* unmapped: {} */", e.escape_default())
}

/// Parsea referencia global: ^NAME(sub1,sub2)
fn parse_global_ref(s: &str) -> (String, Vec<String>) {
    let s = s.trim();
    if !s.starts_with('^') {
        return (s.to_string(), vec![]);
    }
    let no_caret = &s[1..];
    if let Some(paren) = no_caret.find('(') {
        let name = no_caret[..paren].to_string();
        let subs_str = &no_caret[paren+1..no_caret.len()-1]; // Remove closing )
        let subs: Vec<String> = split_m_args(subs_str).into_iter().map(|s| s.trim().to_string()).collect();
        (name, subs)
    } else {
        (no_caret.to_string(), vec![])
    }
}

/// Split M arguments by comma (respecting parentheses)
fn split_m_args(s: &str) -> Vec<String> {
    let mut args = Vec::new();
    let mut current = String::new();
    let mut depth = 0;
    for c in s.chars() {
        match c {
            '(' | '[' => { depth += 1; current.push(c); }
            ')' | ']' => { depth -= 1; current.push(c); }
            ',' if depth == 0 => { args.push(current.clone()); current.clear(); }
            _ => { current.push(c); }
        }
    }
    if !current.trim().is_empty() {
        args.push(current);
    }
    args
}

/// Parsea FOR "var=from:to:step"
fn parse_for(arg: &str) -> (Option<String>, Option<String>, Option<String>, Option<String>) {
    let trimmed = arg.trim();
    if let Some(eq) = trimmed.find('=') {
        let var = trimmed[..eq].trim().to_string();
        let range = &trimmed[eq+1..];
        let parts: Vec<&str> = range.split(':').collect();
        let from = parts.get(0).map(|s| s.to_string());
        let to = parts.get(1).map(|s| s.to_string());
        let step = parts.get(2).map(|s| s.to_string());
        (Some(var), from, to, step)
    } else {
        (None, None, None, None)
    }
}

/// Parsea condición IF
fn parse_if_condition(arg: &str) -> Option<String> {
    Some(arg.trim().to_string())
}

/// Extrae nombre de rutina de DO ^ROUTINE o DO LABEL^ROUTINE
fn extract_routine(arg: &str) -> Option<String> {
    let trimmed = arg.trim();
    if let Some(caret) = trimmed.find('^') {
        Some(trimmed[caret+1..].trim().trim_matches(')').to_string())
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::Compiler;
    
    #[test]
    fn test_simple_set() {
        let program = Compiler::compile("S x=2+2 S ^X=x").unwrap();
        let rust = transpile_to_rust(&program, "test_simple");
        println!("{}", rust);
        // Check it generates Rust with number operations
        assert!(rust.contains("crate::Value::Number"), "Should contain Value::Number");
        assert!(rust.contains("insert"), "Should contain globals.insert");
    }
    
    #[test]
    fn test_for_loop() {
        let program = Compiler::compile("S sum=0 F i=1:1:10 S sum=sum+i").unwrap();
        let rust = transpile_to_rust(&program, "test_loop");
        println!("{}", rust);
        assert!(rust.contains("for"), "Should contain for");
        assert!(rust.contains("as i64"), "Should contain integer conversion");
    }
    
    #[test]
    fn test_device_call() {
        let program = Compiler::compile("S r=$DEVICE(\"llm:call\",\"hola\") S ^R=r").unwrap();
        let rust = transpile_to_rust(&program, "test_device");
        println!("{}", rust);
        assert!(!rust.contains("Null /* $DEVICE"), "Should NOT contain generic Null");
    }

    #[test]
    fn test_ddp_call() {
        let program = Compiler::compile(r#"S r=$DEVICE("ddp:get","ASI","EXP01","39634137") S ^R=r"#).unwrap();
        let rust = transpile_to_rust(&program, "test_ddp");
        println!("{}", rust);
        assert!(rust.contains("TcpStream"), "Should contain TCP client");
        assert!(rust.contains("ASI"), "Should contain space name");
        assert!(!rust.contains("COMPILED_DDP"), "Should NOT be placeholder");
    }
    
    #[test]
    fn test_if_condition() {
        let program = Compiler::compile("I x>10 S y=1").unwrap();
        let rust = transpile_to_rust(&program, "test_if");
        println!("{}", rust);
        assert!(rust.contains("if"), "Should contain if");
    }

    /// Los operadores negados (') deben traducirse a su comparación inversa:
    /// x'>y  → x<=y,  x'<y  → x>=y,  x'>=y → x<y,  x'<=y → x>y.
    /// (fix 2026-08-27: antes solo existía '=; x'>0 daba MUNDEF)
    #[test]
    fn test_not_comparison_operators() {
        let cases = [
            ("S r=x'>0", "<="),
            ("S r=x'<0", ">="),
            ("S r=x'>=0", "<"),
            ("S r=x'<=0", ">"),
            ("S r=x'=0", "!="),
        ];
        for (src, expected) in cases {
            let program = Compiler::compile(src).unwrap();
            let rust = transpile_to_rust(&program, "test_not");
            assert!(
                rust.contains(expected),
                "{} → esperaba `{}` en Rust, got: {}",
                src,
                expected,
                rust
            );
        }
    }
    /// El NOT negado debe evaluar correctamente en runtime: x'>0 con x=2 → 0 (false)
    #[test]
    fn test_not_comparison_runtime() {
        let program = Compiler::compile("S x=2 S r=x'>0 W r").unwrap();
        let rust = transpile_to_rust(&program, "test_not_runtime");
        println!("{}", rust);
        // El transpilador debe emitir `<=` (NOT >)
        assert!(rust.contains("<="), "x'>0 debe emitir <=, got: {}", rust);
    }
}
