use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Opcode {
    Set,
    Kill,
    New,
    If,
    Else,
    For,
    Quit,
    Goto,
    Do,
    Write,
    Read,
    Open,
    Use,
    Close,
    Halt,
    TStart,
    TCommit,
    TRollback,
    Lock,
    Unlock,
    Expr,
    Label,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Instruction {
    pub opcode: Opcode,
    #[serde(default)]
    pub argument: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub postcondition: Option<String>,
    pub line: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Program {
    pub version: String,
    pub source_hash: String,
    pub instructions: Vec<Instruction>,
    pub labels: BTreeMap<String, usize>,
    pub source: String,
}

#[derive(Debug, Default)]
pub struct Compiler;

impl Compiler {
    pub fn compile(source: &str) -> Result<Program, String> {
        Self::compile_with_opts(source, true, 0)
    }

    pub fn compile_inline(source: &str) -> Result<Program, String> {
        Self::compile_with_opts(source, false, 0)
    }

    /// Compila con un offset de línea base (para bodies inline recompilados en
    /// runtime: los errores reportan su línea REAL en el source original, no 1).
    pub fn compile_with_offset(source: &str, line_offset: usize) -> Result<Program, String> {
        Self::compile_with_opts(source, true, line_offset)
    }

    fn compile_with_opts(source: &str, enable_block_collection: bool, line_offset: usize) -> Result<Program, String> {
        let mut instructions = Vec::new();
        let mut labels = BTreeMap::new();
        // Dividir por líneas RESPETANDO strings abiertos: si una línea termina
        // con una comilla sin cerrar (p. ej. un prompt multi-línea dentro de
        // $DEVICE("llm:call","...")), la siguiente línea es continuación del
        // string y NO debe compilarse como código M.
        // Fix 2026-08-09: prompts largos con comillas rompían el parser
        // (MUNDEF/MFUNCTION) porque source.lines() partía el string.
        let lines: Vec<String> = split_lines_respecting_strings(source);
        let mut i = 0;
        while i < lines.len() {
            let raw_line = lines[i].as_str();
            let line_number = i + 1 + line_offset;
            let trimmed = strip_comment(raw_line).trim();
            let (dot_count, line) = split_dots(trimmed);
            if line.is_empty() { i += 1; continue; }
            let (label, rest) = split_label(line);
            let code = if let Some(label) = label {
                labels.insert(label.to_uppercase(), instructions.len());
                instructions.push(Instruction {
                    opcode: Opcode::Label,
                    argument: label.to_string(),
                    postcondition: None,
                    line: line_number,
                });
                rest.trim()
            } else {
                line
            };
            if !code.is_empty() {
                let code_upper = code.trim().to_uppercase();
                let ends_with_do = code_upper.ends_with(" DO") || code_upper.ends_with(" D");
                let has_for = code_upper.contains("FOR")
                    || code_upper.contains(" F ")
                    || code_upper.starts_with("F ");
                let has_if = code_upper.starts_with("IF ")
                    || code_upper.starts_with("I ")
                    || code_upper.contains(" IF ")
                    || code_upper.contains(" I ");
                let for_with_do = ends_with_do && has_for;
                let if_with_do = ends_with_do && has_if && !has_for;

                // Helper: collect body lines at higher dot level
                let mut collect_body = |base_dots: u32, start: usize| -> (String, usize) {
                    let mut body = String::new();
                    let mut j = start;
                    while j < lines.len() {
                        let raw = strip_comment(lines[j].as_str());
                        if raw.trim().is_empty() { j += 1; continue; }
                        let (nd, nline) = split_dots(raw);
                        // Línea de SOLO comentario (`. ; texto`): tras quitar dots y
                        // comentario no queda código → saltarla SIN añadir un DO vacío
                        // al body (un DO sin argumento rompe el bloque → MUNDEF).
                        if nline.trim().is_empty() { j += 1; continue; }
                        if nd > base_dots {
                            // Preservar todos los dots originales para que
                            // la compilación recursiva (FOR DO anidado)
                            // pueda detectar indentación correctamente
                            body.push_str(&".".repeat(nd as usize));
                            body.push(' ');
                            body.push_str(nline.trim());
                            body.push('\n');
                            j += 1;
                        } else { break; }
                    }
                    (body, j)
                };

                if enable_block_collection && for_with_do {
                    let (body_lines, j) = collect_body(dot_count, i + 1);
                    let body_trimmed = format!("{}\n{}", code, body_lines).trim().to_string();
                    if !body_trimmed.is_empty() {
                        compile_line(&body_trimmed, line_number, &mut instructions)?;
                    }
                    i = j - 1;
                } else if enable_block_collection && if_with_do {
                    // IF ... DO with optional ELSE DO
                    let (true_body, j) = collect_body(dot_count, i + 1);
                    let mut false_body = String::new();
                    let mut k = j;
                    // Check if next non-empty line at base dots starts with ELSE/E
                    while k < lines.len() {
                        let nl = strip_comment(lines[k].as_str()).trim();
                        if nl.is_empty() { k += 1; continue; }
                        let (nd, eline) = split_dots(nl);
                        if nd == dot_count {
                            let eu = eline.trim().to_uppercase();
                            if eu.starts_with("ELSE") || eu.starts_with("E ") || eu == "E" {
                                // Collect ELSE body
                                let (else_body, l) = collect_body(dot_count, k + 1);
                                // Fix 2026-08-28 (ELSE con IF anidado): si el ELSE
                                // es `E I cond D`, el false_body DEBE conservar la
                                // condición (`I cond D\n...`) — antes solo guardaba
                                // el body → la rama se ejecutaba SIEMPRE sin evaluar
                                // su condición (cadena `I a D ... E I b D ... E I c D`
                                // → "b" y "c" se disparaban con a=false).
                                // El eline es "E  I cond D": quitar el prefijo E/ELSE
                                // y comprobar si el resto es un IF.
                                let after_else = eline
                                    .trim()
                                    .trim_start_matches(|c: char| c == 'E' || c.is_whitespace())
                                    .trim_start_matches("LSE")
                                    .trim_start();
                                let after_upper = after_else.to_uppercase();
                                if after_upper.starts_with("I ") || after_upper.starts_with("IF ") {
                                    false_body = format!("{}\n{}", after_else, else_body);
                                } else {
                                    false_body = else_body;
                                }
                                k = l;
                                break;
                            }
                        }
                        break;
                    }
                    // Strip trailing DO/D from IF line since blocks are already collected
                    let condition = code.trim_end_matches(" DO").trim_end_matches(" D");
                    let if_arg = format!("{}{}{}{}{}", condition, "\x01", true_body.trim(), "\x01", false_body.trim());
                    compile_line(&if_arg, line_number, &mut instructions)?;
                    i = k - 1;  // Skip ELSE and its body too
                } else {
                    compile_line(code, line_number, &mut instructions)?;
                }
            }
            i += 1;
        }
        let source_hash = format!("{:x}", Sha256::digest(source.as_bytes()));
        Ok(Program {
            version: crate::vm::VM_VERSION.to_string(),
            source_hash,
            instructions,
            labels,
            source: source.to_string(),
        })
    }
}

/// Divide el source en líneas lógicas, pero SI una línea termina con un
/// string M abierto (comilla sin cerrar), continúa acumulando las siguientes
/// líneas dentro del mismo string. Así un prompt multi-línea embebido en
/// $DEVICE("llm:call","...") no se parte en comandos M inválidos.
fn split_lines_respecting_strings(source: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut current = String::new();
    let mut quoted = false;
    // Iterar por CHARS (no bytes): `b as char` corrompía el unicode
    // (0xC3 0xA1 = "á" se convertía en "Ã¡" — mojibake en TODO el source
    // con acentos, fix 2026-08-27: $L("áβ")=4 en vez de 2).
    let chars: Vec<char> = source.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let ch = chars[i];
        if ch == '\n' {
            if quoted {
                // String abierto: el newline es parte del literal
                current.push('\n');
            } else {
                lines.push(std::mem::take(&mut current));
            }
            i += 1;
            continue;
        }
        if ch == '"' {
            if quoted && i + 1 < chars.len() && chars[i + 1] == '"' {
                // Comilla escapada ("") dentro de string — se conserva tal cual
                current.push('"');
                current.push('"');
                i += 2;
                continue;
            }
            quoted = !quoted;
        }
        current.push(ch);
        i += 1;
    }
    if !current.is_empty() {
        lines.push(current);
    }
    lines
}

fn strip_comment(line: &str) -> &str {
    let mut quoted = false;
    let bytes = line.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            if quoted && i + 1 < bytes.len() && bytes[i + 1] == b'"' {
                i += 2;
                continue;
            }
            quoted = !quoted;
        } else if bytes[i] == b';' && !quoted {
            return &line[..i];
        }
        i += 1;
    }
    line
}

fn split_label(line: &str) -> (Option<&str>, &str) {
    // Label ends at first whitespace OR '(' (parameter list), whichever is FIRST
    let ws = line.find(char::is_whitespace).unwrap_or(line.len());
    let paren = line.find('(').unwrap_or(line.len());
    let token_end = ws.min(paren);
    let first = &line[..token_end];
    // Fix 2026-08-28 (etiquetas en minúsculas): antes exigía solo MAYÚSCULAS
    // (`!ch.is_ascii_lowercase() && ch != '_'`) → `D mover(n,lugar)` con etiqueta
    // `mover` daba MLABEL. Los LLM generan etiquetas camelCase/snake_case;
    // MUMPS canónico también las permite. `opcode(first)` ya filtra comandos
    // (case-insensitive), así que un identificador que no es comando es etiqueta.
    if is_identifier(first) && opcode(first).is_none() {
        // If label has parameters (x), consume the (...) block
        let after_label = &line[token_end..].trim_start();
        let after_params = if after_label.starts_with('(') {
            // Find matching close paren
            let mut depth = 0i32;
            let mut close = 0usize;
            for (i, ch) in after_label.char_indices() {
                if ch == '(' { depth += 1; }
                else if ch == ')' { depth -= 1; if depth == 0 { close = i + 1; break; } }
            }
            if close > 0 { &after_label[close..] } else { after_label }
        } else {
            after_label
        };
        (Some(first), after_params)
    } else {
        (None, line)
    }
}

fn is_identifier(value: &str) -> bool {
    let mut chars = value.chars();
    chars
        .next()
        .is_some_and(|ch| ch.is_ascii_alphabetic() || ch == '%')
        && chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '%')
}

/// Split leading dots from a line and return (dot_count, rest_without_dots)
fn split_dots(line: &str) -> (u32, &str) {
    let mut trimmed = line.trim_start();
    let mut count = 0u32;
    loop {
        if trimmed.starts_with('.') {
            count += 1;
            trimmed = trimmed[1..].trim_start();
        } else {
            break;
        }
    }
    (count, trimmed)
}

fn opcode(token: &str) -> Option<Opcode> {
    match token.to_ascii_uppercase().as_str() {
        "S" | "SET" => Some(Opcode::Set),
        "K" | "KILL" => Some(Opcode::Kill),
        "N" | "NEW" => Some(Opcode::New),
        "I" | "IF" => Some(Opcode::If),
        "E" | "ELSE" => Some(Opcode::Else),
        "F" | "FOR" => Some(Opcode::For),
        "Q" | "QUIT" => Some(Opcode::Quit),
        "G" | "GOTO" => Some(Opcode::Goto),
        "D" | "DO" => Some(Opcode::Do),
        "W" | "WRITE" => Some(Opcode::Write),
        "R" | "READ" => Some(Opcode::Read),
        "O" | "OPEN" => Some(Opcode::Open),
        "U" | "USE" => Some(Opcode::Use),
        "C" | "CLOSE" => Some(Opcode::Close),
        "H" | "HALT" => Some(Opcode::Halt),
        "TS" | "TSTART" => Some(Opcode::TStart),
        "TC" | "TCOMMIT" => Some(Opcode::TCommit),
        "TR" | "TROLLBACK" => Some(Opcode::TRollback),
        "L" | "LOCK" => Some(Opcode::Lock),
        "UNLOCK" => Some(Opcode::Unlock),
        _ => None,
    }
}

fn compile_line(
    line: &str,
    line_number: usize,
    instructions: &mut Vec<Instruction>,
) -> Result<(), String> {
    let mut rest = line.trim();
    while !rest.is_empty() {
        // Saltar dots (marcadores de bloque) para compilación recursiva
        rest = rest.trim_start_matches('.').trim_start();
        if rest.is_empty() { break; }
        let token_end = rest.find(char::is_whitespace).unwrap_or(rest.len());
        let raw_token = &rest[..token_end];
        let (command_token, postcondition) = raw_token
            .split_once(':')
            .map_or((raw_token, None), |(command, condition)| {
                // Postcondition may include subsequent commands — trim at next boundary
                let boundary = next_command_boundary(condition);
                (command, Some(condition[..boundary].trim().to_string()))
            });
        let Some(command) = opcode(command_token) else {
            instructions.push(Instruction {
                opcode: Opcode::Expr,
                argument: rest.to_string(),
                postcondition: None,
                line: line_number,
            });
            break;
        };
        if matches!(command, Opcode::For) {
            // Bypass the whole FOR parser until we properly handle it
            // FOR loop body collection is done in a single pass below
        }
        let after_token = rest[token_end..].trim_start();
        if matches!(command, Opcode::For) {
            // (removed debug)
        }
        let consumes_remainder = matches!(command, Opcode::If | Opcode::Else | Opcode::For);
        let has_no_argument = matches!(
            command,
            Opcode::Halt | Opcode::TStart | Opcode::TCommit | Opcode::TRollback
        );
        // For Quit: if next token after postcondition is a command opcode, it has no explicit argument
        let is_quit_no_arg = matches!(command, Opcode::Quit)
            && after_token.trim_start().split_whitespace().next()
                .map_or(false, |tok| opcode(tok.split(':').next().unwrap_or(tok)).is_some());
        let boundary = if has_no_argument || is_quit_no_arg {
            0
        } else if matches!(command, Opcode::For) || consumes_remainder {
            after_token.len()
        } else {
            next_command_boundary(after_token)
        };
        let argument = after_token[..boundary].trim().to_string();
        if matches!(command, Opcode::For) {
            // (removed debug)
        }
        instructions.push(Instruction {
            opcode: command,
            argument,
            postcondition,
            line: line_number,
        });
        rest = after_token[boundary..].trim_start();
    }
    Ok(())
}

fn next_command_boundary(value: &str) -> usize {
    let mut depth = 0i32;
    let mut braces = 0i32;
    let mut quoted = false;
    let bytes = value.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => {
                if quoted && i + 1 < bytes.len() && bytes[i + 1] == b'"' {
                    i += 2;
                    continue;
                }
                quoted = !quoted;
            }
            b'(' if !quoted => depth += 1,
            b')' if !quoted => depth -= 1,
            b'{' if !quoted => braces += 1,
            b'}' if !quoted => braces -= 1,
            byte if byte.is_ascii_whitespace() && !quoted && depth == 0 && braces == 0 => {
                let candidate = value[i..].trim_start();
                // No cortar si el espacio está pegado a un operador binario o
                // separador M ("t + i", "a * b", "W \"x\", var", "s = a _ b"):
                // el token siguiente sería un operando, no un comando
                // ("i" colisiona con IF, "e" con ELSE, "n" con NEW, etc.).
                // Lista COMPLETA de operadores/separadores M (fix 26-08-2026):
                // aritmética (+ - * / \ # **), concat (_), comparación (= < > <= >= '= != [ ]),
                // lógicos (& !), negación ('), separador de argumentos (,).
                if i > 0
                    && matches!(
                        value.as_bytes()[i - 1],
                        b'+' | b'-' | b'*' | b'/' | b'\\' | b'#' | b'=' | b'<' | b'>'
                            | b'_' | b'\'' | b'&' | b',' | b'[' | b']'
                    )
                {
                    i += 1;
                    continue;
                }
                let end = candidate
                    .find(char::is_whitespace)
                    .unwrap_or(candidate.len());
                let token = candidate[..end].split(':').next().unwrap_or_default();
                if token == "." {
                    // Dot block marker — treat as command boundary
                    return i;
                }
                if opcode(token).is_some() {
                    return i;
                }
            }
            _ => {}
        }
        i += 1;
    }
    value.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compiles_multiple_commands_and_labels() {
        let program = Compiler::compile("S a=1 S b=2\nSUB\nS c=a+b Q").unwrap();
        assert_eq!(program.instructions.len(), 5);
        assert_eq!(program.instructions[0].opcode, Opcode::Set);
        assert_eq!(program.instructions[1].opcode, Opcode::Set);
        assert_eq!(program.labels["SUB"], 2);
    }

    #[test]
    fn comments_respect_strings() {
        let program = Compiler::compile("W \"a;b\" ; real comment").unwrap();
        assert_eq!(program.instructions[0].argument, "\"a;b\"");
    }

    /// Fix 2026-08-28: cadena IF/ELSE con IF anidado — `I a D ... E I b D ...
    /// E I c D`. El compilador perdía la condición de las ramas intermedias
    /// (false_body sin "I cond D") → se ejecutaban siempre (pueblo: escasez
    /// y rumor se disparaban con evento="").
    #[test]
    fn else_if_chain_keeps_conditions() {
        let cases: Vec<(&str, &str)> = vec![
            ("S ev=\"\"\nI ev=\"fiesta\" D\n. S ^E=\"fi\"\nE  I ev=\"escasez\" D\n. S ^E=\"es\"\nE  I ev=\"rumor\" D\n. S ^E=\"ru\"\nW $G(^E) Q", ""),
            ("S ev=\"escasez\"\nI ev=\"fiesta\" D\n. S ^E=\"fi\"\nE  I ev=\"escasez\" D\n. S ^E=\"es\"\nE  I ev=\"rumor\" D\n. S ^E=\"ru\"\nW $G(^E) Q", "es"),
            ("S ev=\"rumor\"\nI ev=\"fiesta\" D\n. S ^E=\"fi\"\nE  I ev=\"escasez\" D\n. S ^E=\"es\"\nE  I ev=\"rumor\" D\n. S ^E=\"ru\"\nW $G(^E) Q", "ru"),
            ("S ev=\"fiesta\"\nI ev=\"fiesta\" D\n. S ^E=\"fi\"\nE  I ev=\"escasez\" D\n. S ^E=\"es\"\nE  I ev=\"rumor\" D\n. S ^E=\"ru\"\nW $G(^E) Q", "fi"),
            // ELSE final simple después de cadena (E D)
            ("S ev=\"x\"\nI ev=\"fiesta\" D\n. S ^E=\"fi\"\nE  I ev=\"escasez\" D\n. S ^E=\"es\"\nE  D\n. S ^E=\"otro\"\nW $G(^E) Q", "otro"),
        ];
        for (code, want) in cases {
            let program = crate::compiler::Compiler::compile(code).unwrap();
            let mut host = crate::MemoryHost::default();
            let mut vm = crate::Vm::new(program, &mut host);
            let execution = vm.run();
            assert!(!matches!(execution, crate::Execution::Error), "{code:?} got {execution:?}");
            assert_eq!(vm.state.output, want, "salida para {code:?}");
        }
    }

    /// Fix 2026-08-28: operadores lógicos ! y & entre comparaciones
    /// (`a=""!b=""` = OR). Antes find_comparison dividía mal → MUNDEF.
    #[test]
    fn logical_or_and() {
        let cases: Vec<(&str, &str)> = vec![
            ("S a=\"\" S b=\"\" W a=\"\"!b=\"\" Q", "1"),
            ("S a=\"x\" S b=\"\" W a=\"\"!b=\"\" Q", "1"),
            ("S a=\"x\" S b=\"y\" W a=\"\"!b=\"\" Q", "0"),
            ("S a=\"x\" S b=\"y\" W a'=\"\"&b'=\"\" Q", "1"),
            ("S a=\"\" S b=\"y\" W a'=\"\"&b'=\"\" Q", "0"),
            ("S a=3 I a>1&a<5 W \"and\" Q", "and"),
            ("S a=3 I a>5!a<4 W \"or\" Q", "or"),
        ];
        for (code, want) in cases {
            let program = crate::compiler::Compiler::compile(code).unwrap();
            let mut host = crate::MemoryHost::default();
            let mut vm = crate::Vm::new(program, &mut host);
            let execution = vm.run();
            assert!(!matches!(execution, crate::Execution::Error), "{code:?} got {execution:?}");
            assert_eq!(vm.state.output, want, "salida para {code:?}");
        }
    }

    /// Fix 2026-08-28: operador potencia `**` (MUMPS). Los LLM lo generan
    /// (p.ej. dist=(dx*dx+dy*dy)**0.5). Antes: MOPERATOR unknown.
    #[test]
    fn power_operator() {
        let cases: Vec<(&str, &str)> = vec![
            ("W 2**3 Q", "8"),
            ("W 2**0.5 Q", "1.4142135623730951"),
            ("S a=3 W a**2 Q", "9"),
            ("W (5*5+5*5)**0.5 Q", "7.0710678118654755"),
        ];
        for (code, want) in cases {
            let program = crate::compiler::Compiler::compile(code).unwrap();
            let mut host = crate::MemoryHost::default();
            let mut vm = crate::Vm::new(program, &mut host);
            let execution = vm.run();
            assert!(!matches!(execution, crate::Execution::Error), "{code:?} got {execution:?}");
            assert_eq!(vm.state.output, want, "salida para {code:?}");
        }
    }

    /// Fix 2026-08-28: etiquetas en minúsculas/camelCase (mover, calcTotal).
    /// Antes split_label exigía solo MAYÚSCULAS → `D mover(x)` daba MLABEL.
    #[test]
    fn labels_lowercase_and_camelcase() {
        let program = Compiler::compile("D mover(1)\nQ\nmover(a)\nS ^R=1\nQ").unwrap();
        assert!(program.labels.contains_key("MOVER"), "labels={:?}", program.labels);
        let program2 = Compiler::compile("D calcTotal(1)\nQ\ncalcTotal(n)\nS ^T=2\nQ").unwrap();
        assert!(program2.labels.contains_key("CALCTOTAL"), "labels={:?}", program2.labels);
    }
}
