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
}

#[derive(Debug, Default)]
pub struct Compiler;

impl Compiler {
    pub fn compile(source: &str) -> Result<Program, String> {
        Self::compile_with_opts(source, true)
    }

    pub fn compile_inline(source: &str) -> Result<Program, String> {
        Self::compile_with_opts(source, false)
    }

    fn compile_with_opts(source: &str, enable_block_collection: bool) -> Result<Program, String> {
        let mut instructions = Vec::new();
        let mut labels = BTreeMap::new();
        let lines: Vec<&str> = source.lines().collect();
        let mut i = 0;
        while i < lines.len() {
            let raw_line = lines[i];
            let line_number = i + 1;
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
                        let nl = strip_comment(lines[j]).trim();
                        if nl.is_empty() { j += 1; continue; }
                        let (nd, _) = split_dots(nl);
                        if nd > base_dots {
                            let (_, nline) = split_dots(nl);
                            body.push_str(&"  ".repeat((nd - base_dots - 1) as usize));
                            body.push_str(nline);
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
                        let nl = strip_comment(lines[k]).trim();
                        if nl.is_empty() { k += 1; continue; }
                        let (nd, eline) = split_dots(nl);
                        if nd == dot_count {
                            let eu = eline.trim().to_uppercase();
                            if eu.starts_with("ELSE") || eu.starts_with("E ") || eu == "E" {
                                // Collect ELSE body
                                let (else_body, l) = collect_body(dot_count, k + 1);
                                false_body = else_body;
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
        })
    }
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
    if is_identifier(first)
        && first.chars().all(|ch| !ch.is_ascii_lowercase() && ch != '_')
        && opcode(first).is_none()
    {
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
        let after_token = rest[token_end..].trim_start();
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
        } else if consumes_remainder {
            after_token.len()
        } else {
            next_command_boundary(after_token)
        };
        let argument = after_token[..boundary].trim().to_string();
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
                let end = candidate
                    .find(char::is_whitespace)
                    .unwrap_or(candidate.len());
                let token = candidate[..end].split(':').next().unwrap_or_default();
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
}
