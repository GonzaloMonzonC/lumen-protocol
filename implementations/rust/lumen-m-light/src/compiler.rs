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
        let mut instructions = Vec::new();
        let mut labels = BTreeMap::new();
        for (line_index, raw_line) in source.lines().enumerate() {
            let line_number = line_index + 1;
            let line = strip_comment(raw_line).trim();
            if line.is_empty() {
                continue;
            }
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
                compile_line(code, line_number, &mut instructions)?;
            }
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
    let first_end = line.find(char::is_whitespace).unwrap_or(line.len());
    let first = &line[..first_end];
    if is_identifier(first)
        && first.chars().all(|ch| !ch.is_ascii_lowercase() && ch != '_')
        && opcode(first).is_none()
    {
        (Some(first), &line[first_end..])
    } else {
        (None, line)
    }
}

fn is_identifier(value: &str) -> bool {
    let mut chars = value.chars();
    chars
        .next()
        .is_some_and(|ch| ch.is_ascii_alphabetic() || ch == '%')
        && chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '%' || ch == '_')
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
                (command, Some(condition.to_string()))
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
            Opcode::Quit | Opcode::Halt | Opcode::TStart | Opcode::TCommit | Opcode::TRollback
        );
        let boundary = if has_no_argument {
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
