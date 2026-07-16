use crate::compiler::{Compiler, Instruction, Opcode, Program};
use crate::host::Host;
use crate::{Subscript, Value};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::time::{SystemTime, UNIX_EPOCH};

/// Días $HOROLOG del epoch Unix (día 0 = 1840-12-31).
const HOROLOG_UNIX_EPOCH_DAYS: u64 = 47117;

pub const VM_VERSION: &str = "3.0.0-rust";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct VmError {
    pub ecode: String,
    pub zerror: String,
    #[serde(default)]
    pub line: usize,
}

impl VmError {
    fn new(code: &str, message: impl Into<String>, line: usize) -> Self {
        Self {
            ecode: code.to_string(),
            zerror: message.into(),
            line,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct VmState {
    pub version: String,
    pub program_hash: String,
    #[serde(default)]
    pub job_id: i64,
    pub ip: usize,
    #[serde(default)]
    pub stack: Vec<Value>,
    #[serde(default)]
    pub vars: BTreeMap<String, Value>,
    #[serde(default)]
    pub call_stack: Vec<usize>,
    #[serde(default)]
    pub loop_frames: BTreeMap<usize, LoopFrame>,
    #[serde(default)]
    pub local_scopes: Vec<LocalScope>,
    #[serde(default)]
    pub argument_scopes: Vec<BTreeMap<String, Option<Value>>>,
    #[serde(default)]
    pub output: String,
    #[serde(default = "default_io")]
    pub current_io: i64,
    #[serde(default = "default_gas_limit")]
    pub gas_limit: u64,
    #[serde(default)]
    pub gas_budget: u64,
    #[serde(default)]
    pub gas_used: u64,
    #[serde(default)]
    pub halted: bool,
    /// $TEST: resultado del último LOCK con timeout.
    #[serde(default)]
    pub test: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<VmError>,
}

fn default_io() -> i64 {
    0
}

fn default_gas_limit() -> u64 {
    1000
}

impl VmState {
    pub fn new(program: &Program) -> Self {
        Self {
            version: VM_VERSION.to_string(),
            program_hash: program.source_hash.clone(),
            job_id: 0,
            ip: 0,
            stack: Vec::new(),
            vars: BTreeMap::new(),
            call_stack: Vec::new(),
            loop_frames: BTreeMap::new(),
            local_scopes: Vec::new(),
            argument_scopes: Vec::new(),
            output: String::new(),
            current_io: 0,
            gas_limit: default_gas_limit(),
            gas_budget: 0,
            gas_used: 0,
            halted: false,
            test: false,
            error: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Execution {
    Completed,
    Yielded,
    Halted,
    Error,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LoopFrame {
    variable: Option<String>,
    current: f64,
    step: f64,
    limit: Option<f64>,
    body: String,
    body_ip: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct LocalScope {
    call_depth: usize,
    #[serde(default)]
    all: bool,
    variables: BTreeMap<String, Option<Value>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Control {
    Continue,
    Quit,
    Halt,
    Yield,
}

pub struct Vm<'a, H: Host> {
    pub program: Program,
    pub state: VmState,
    pub host: &'a mut H,
    slice_used: u64,
    slice_limit: u64,
    /// >0 mientras se ejecuta código inline (D ^RUTINA, cuerpos IF/ELSE).
    /// El agotamiento de slice NO cede ahí: una rutina reiniciada a mitad
    /// repite efectos (livelock con FOR). gas_budget sí sigue aplicando.
    inline_depth: usize,
}

impl<'a, H: Host> Vm<'a, H> {
    pub fn new(program: Program, host: &'a mut H) -> Self {
        let state = VmState::new(&program);
        Self {
            program,
            state,
            host,
            slice_used: 0,
            slice_limit: 1,
            inline_depth: 0,
        }
    }

    pub fn resume(program: Program, state: VmState, host: &'a mut H) -> Result<Self, VmError> {
        if state.version != VM_VERSION {
            return Err(VmError::new("MVERSION", "VM version mismatch", 0));
        }
        if state.program_hash != program.source_hash {
            return Err(VmError::new("MPROGRAM", "program hash mismatch", 0));
        }
        Ok(Self {
            program,
            state,
            host,
            slice_used: 0,
            slice_limit: 1,
            inline_depth: 0,
        })
    }

    pub fn run(&mut self) -> Execution {
        self.run_slice(self.state.gas_limit)
    }

    pub fn run_slice(&mut self, gas: u64) -> Execution {
        self.slice_used = 0;
        self.slice_limit = gas.max(1);
        while self.state.ip < self.program.instructions.len() && !self.state.halted {
            if self.slice_used >= self.slice_limit && self.host.transaction_level() == 0 {
                return Execution::Yielded;
            }
            let instruction = self.program.instructions[self.state.ip].clone();
            self.state.ip += 1;
            if let Err(error) = self.charge(instruction.line) {
                self.rollback_open_transactions();
                self.state.error = Some(error);
                self.state.halted = true;
                return Execution::Error;
            }
            match self.execute_instruction(&instruction) {
                Ok(Control::Continue) => {}
                Ok(Control::Quit) => {
                    self.restore_local_scopes();
                    self.restore_arguments();
                    if let Some(return_ip) = self.state.call_stack.pop() {
                        self.state.ip = return_ip;
                    } else {
                        self.state.halted = true;
                    }
                }
                Ok(Control::Halt) => self.state.halted = true,
                Ok(Control::Yield) => return Execution::Yielded,
                Err(error) => {
                    self.rollback_open_transactions();
                    self.state.error = Some(error);
                    self.state.halted = true;
                    return Execution::Error;
                }
            }
        }
        if self.state.error.is_some() {
            Execution::Error
        } else if self.state.halted {
            Execution::Halted
        } else {
            Execution::Completed
        }
    }

    fn charge(&mut self, line: usize) -> Result<(), VmError> {
        if self.state.gas_budget > 0 && self.state.gas_used >= self.state.gas_budget {
            return Err(VmError::new("GAS_EXHAUSTED", "gas budget exhausted", line));
        }
        self.state.gas_used += 1;
        self.slice_used += 1;
        Ok(())
    }

    fn rollback_open_transactions(&mut self) {
        while self.host.transaction_level() > 0 {
            if self.host.transaction_rollback().is_err() {
                break;
            }
        }
    }

    fn restore_local_scopes(&mut self) {
        let depth = self.state.call_stack.len();
        while self
            .state
            .local_scopes
            .last()
            .is_some_and(|scope| scope.call_depth >= depth)
        {
            if let Some(scope) = self.state.local_scopes.pop() {
                self.restore_scope(scope);
            }
        }
    }

    fn restore_local_scopes_to(&mut self, base: usize) {
        while self.state.local_scopes.len() > base {
            if let Some(scope) = self.state.local_scopes.pop() {
                self.restore_scope(scope);
            }
        }
    }

    fn restore_scope(&mut self, scope: LocalScope) {
        if scope.all {
            self.state.vars.clear();
        }
        for (name, value) in scope.variables {
            if let Some(value) = value {
                self.state.vars.insert(name, value);
            } else {
                self.state.vars.remove(&name);
            }
        }
    }

    fn bind_arguments(&mut self, arguments: Vec<Value>) {
        let mut previous = BTreeMap::new();
        for (index, value) in arguments.into_iter().enumerate() {
            let name = format!("${}", index + 1);
            previous.insert(name.clone(), self.state.vars.get(&name).cloned());
            self.state.vars.insert(name, value);
        }
        self.state.argument_scopes.push(previous);
    }

    fn restore_arguments(&mut self) {
        if let Some(previous) = self.state.argument_scopes.pop() {
            for (name, value) in previous {
                if let Some(value) = value {
                    self.state.vars.insert(name, value);
                } else {
                    self.state.vars.remove(&name);
                }
            }
        }
    }

    fn execute_instruction(&mut self, instruction: &Instruction) -> Result<Control, VmError> {
        if let Some(condition) = instruction.postcondition.as_deref() {
            if !self.eval_expr(condition, instruction.line)?.truthy() {
                return Ok(Control::Continue);
            }
        }
        match instruction.opcode {
            Opcode::Set => self.exec_set(&instruction.argument, instruction.line)?,
            Opcode::Kill => self.exec_kill(&instruction.argument, instruction.line)?,
            Opcode::New => {
                let mut variables = BTreeMap::new();
                let all = instruction.argument.trim().is_empty();
                let names = if all {
                    self.state.vars.keys().cloned().collect()
                } else {
                    split_top_level(&instruction.argument, ',')
                };
                for name in &names {
                    let name = name.trim();
                    variables.insert(name.to_string(), self.state.vars.get(name).cloned());
                }
                self.state.local_scopes.push(LocalScope {
                    call_depth: self.state.call_stack.len(),
                    all,
                    variables,
                });
                for name in names {
                    self.state.vars.remove(name.trim());
                }
            }
            Opcode::If => return self.exec_if(&instruction.argument, instruction.line),
            Opcode::Else => self.exec_inline(&instruction.argument, instruction.line)?,
            Opcode::For => return self.exec_for(&instruction.argument, instruction.line),
            Opcode::Quit => return Ok(Control::Quit),
            Opcode::Goto => {
                let label = instruction
                    .argument
                    .split_whitespace()
                    .next()
                    .unwrap_or_default();
                self.state.ip = self.label_ip(label, instruction.line)?;
            }
            Opcode::Do => return self.exec_do(&instruction.argument, instruction.line),
            Opcode::Write => self.exec_write(&instruction.argument, instruction.line)?,
            Opcode::Read => {
                self.exec_read(&instruction.argument, instruction.line)?;
                if self.host.read_would_block() {
                    self.state.ip = self.state.ip.saturating_sub(1);
                    return Ok(Control::Yield);
                }
            }
            Opcode::Open | Opcode::Close => {}
            Opcode::Use => {
                self.state.current_io = self
                    .eval_expr(&instruction.argument, instruction.line)?
                    .as_number() as i64;
            }
            Opcode::Halt => return Ok(Control::Halt),
            Opcode::TStart => self
                .host
                .transaction_start()
                .map_err(|e| VmError::new("MTRANSACTION", e, instruction.line))?,
            Opcode::TCommit => self
                .host
                .transaction_commit()
                .map_err(|e| VmError::new("MTRANSACTION", e, instruction.line))?,
            Opcode::TRollback => self
                .host
                .transaction_rollback()
                .map_err(|e| VmError::new("MTRANSACTION", e, instruction.line))?,
            Opcode::Lock => return self.exec_lock(&instruction.argument, instruction.line),
            Opcode::Unlock => self.exec_unlock(&instruction.argument, instruction.line)?,
            Opcode::Expr => {
                let value = self.eval_expr(&instruction.argument, instruction.line)?;
                self.state.stack.push(value);
            }
            Opcode::Label => {}
        }
        Ok(Control::Continue)
    }

    fn label_ip(&self, label: &str, line: usize) -> Result<usize, VmError> {
        self.program
            .labels
            .get(&label.trim_start_matches('^').to_uppercase())
            .copied()
            .ok_or_else(|| VmError::new("MLABEL", format!("unknown label {label}"), line))
    }

    fn exec_do(&mut self, argument: &str, line: usize) -> Result<Control, VmError> {
        let target = argument.split_whitespace().next().unwrap_or_default();
        let (target_name, raw_arguments) = split_call_target(target);
        let arguments = split_top_level(raw_arguments, ',')
            .into_iter()
            .filter(|value| !value.is_empty())
            .map(|value| self.eval_expr(&value, line))
            .collect::<Result<Vec<_>, _>>()?;
        if target_name.starts_with('^') {
            let name = target_name.trim_start_matches('^').trim();
            let source = self
                .host
                .routine(name)
                .map_err(|e| VmError::new("MROUTINE", e, line))?
                .ok_or_else(|| VmError::new("MROUTINE", format!("unknown routine {name}"), line))?;
            self.bind_arguments(arguments);
            let scope_base = self.state.local_scopes.len();
            let result = self.exec_inline_control(&source, line);
            self.restore_local_scopes_to(scope_base);
            self.restore_arguments();
            let control = result?;
            return Ok(match control {
                Control::Halt => Control::Halt,
                _ => Control::Continue,
            });
        } else {
            let destination = self.label_ip(target_name, line)?;
            self.bind_arguments(arguments);
            self.state.call_stack.push(self.state.ip);
            self.state.ip = destination;
        }
        Ok(Control::Continue)
    }

    /// `LOCK ^NS(subs)[:timeout]` — spec §4. Sin timeout la VM bloquea
    /// cooperativamente: un intento no bloqueante y, si falla, rebobina el IP
    /// y cede el slice (el scheduler reintenta la misma instrucción). Con
    /// timeout el resultado queda en $TEST y la ejecución continúa.
    /// `LOCK` sin argumento libera todos los locks del job (M estándar).
    fn exec_lock(&mut self, argument: &str, line: usize) -> Result<Control, VmError> {
        let argument = argument.trim();
        if argument.is_empty() {
            self.host
                .unlock_all()
                .map_err(|e| VmError::new("MLOCK", e, line))?;
            return Ok(Control::Continue);
        }
        let (reference, timeout) = match find_top_level(argument, ":") {
            Some(index) => {
                let timeout = self
                    .eval_expr(argument[index + 1..].trim(), line)?
                    .as_number()
                    .max(0.0);
                (argument[..index].trim(), Some(timeout))
            }
            None => (argument, None),
        };
        let resolved = self.resolve_target(reference, line)?;
        let (ns, subs) = self.parse_global(&resolved, line)?;
        let acquired = self
            .host
            .lock(&ns, &subs, timeout)
            .map_err(|e| VmError::new("MLOCK", e, line))?;
        if timeout.is_some() {
            self.state.test = acquired;
        } else if !acquired {
            self.state.ip = self.state.ip.saturating_sub(1);
            return Ok(Control::Yield);
        }
        Ok(Control::Continue)
    }

    /// `UNLOCK ^NS(subs)[,...]` — sin argumento libera todos los del job.
    fn exec_unlock(&mut self, argument: &str, line: usize) -> Result<(), VmError> {
        let argument = argument.trim();
        if argument.is_empty() {
            return self
                .host
                .unlock_all()
                .map_err(|e| VmError::new("MLOCK", e, line));
        }
        for raw in split_top_level(argument, ',') {
            let resolved = self.resolve_target(raw.trim(), line)?;
            let (ns, subs) = self.parse_global(&resolved, line)?;
            self.host
                .unlock(&ns, &subs)
                .map_err(|e| VmError::new("MLOCK", e, line))?;
        }
        Ok(())
    }

    fn exec_set(&mut self, argument: &str, line: usize) -> Result<(), VmError> {
        for assignment in split_top_level(argument, ',') {
            let Some(index) = find_top_level(&assignment, "=") else {
                return Err(VmError::new("MSET", "assignment requires =", line));
            };
            let target = assignment[..index].trim();
            let expression = assignment[index + 1..].trim();
            let value = self.eval_expr(expression, line)?;
            self.assign(target, value.clone(), line)?;
            self.state.stack.push(value);
        }
        Ok(())
    }

    fn assign(&mut self, target: &str, value: Value, line: usize) -> Result<(), VmError> {
        let resolved = self.resolve_target(target, line)?;
        if resolved.starts_with('^') {
            let (ns, subs) = self.parse_global(&resolved, line)?;
            self.host
                .set(&ns, &subs, value)
                .map_err(|e| VmError::new("MSET", e, line))
        } else if is_identifier(&resolved) {
            self.state.vars.insert(resolved, value);
            Ok(())
        } else {
            Err(VmError::new(
                "MSET",
                format!("invalid target {target}"),
                line,
            ))
        }
    }

    fn resolve_target(&mut self, target: &str, line: usize) -> Result<String, VmError> {
        let target = target.trim();
        if let Some(indirect) = target.strip_prefix('@') {
            let expression = indirect
                .strip_prefix('(')
                .and_then(|v| v.strip_suffix(')'))
                .unwrap_or(indirect);
            let resolved = self.eval_expr(expression, line)?.as_string();
            if resolved.is_empty() {
                Err(VmError::new("MINDIRECT", "empty indirect target", line))
            } else {
                Ok(resolved)
            }
        } else {
            Ok(target.to_string())
        }
    }

    fn exec_kill(&mut self, argument: &str, line: usize) -> Result<(), VmError> {
        for raw in split_top_level(argument, ',') {
            let target = self.resolve_target(raw.trim(), line)?;
            if target.starts_with('^') {
                let (ns, subs) = self.parse_global(&target, line)?;
                self.host
                    .kill(&ns, &subs)
                    .map_err(|e| VmError::new("MKILL", e, line))?;
            } else {
                self.state.vars.remove(&target);
            }
        }
        Ok(())
    }

    fn exec_if(&mut self, argument: &str, line: usize) -> Result<Control, VmError> {
        let (condition, true_body, false_body) = split_if(argument);
        let selected = if self.eval_expr(condition, line)?.truthy() {
            true_body
        } else {
            false_body
        };
        if !selected.is_empty() {
            return self.exec_inline_control(selected, line);
        }
        Ok(Control::Continue)
    }

    fn exec_for(&mut self, argument: &str, line: usize) -> Result<Control, VmError> {
        let argument = argument.trim();
        if argument.is_empty() {
            return Ok(Control::Continue);
        }
        let instruction_ip = self.state.ip.saturating_sub(1);
        let mut frame = if let Some(frame) = self.state.loop_frames.remove(&instruction_ip) {
            frame
        } else {
            let (specification, raw_body) = split_for_body(argument);
            if let Some(equal) = find_top_level(specification, "=") {
                let variable = specification[..equal].trim().to_string();
                let range = &specification[equal + 1..];
                let parts = split_top_level(range, ':');
                let start = self
                    .eval_expr(parts.first().map_or("1", String::as_str), line)?
                    .as_number();
                let step = self
                    .eval_expr(parts.get(1).map_or("1", String::as_str), line)?
                    .as_number();
                let limit = parts
                    .get(2)
                    .map(|value| self.eval_expr(value, line).map(|v| v.as_number()))
                    .transpose()?;
                LoopFrame {
                    variable: Some(variable),
                    current: start,
                    step,
                    limit,
                    body: strip_block(raw_body).to_string(),
                    body_ip: 0,
                }
            } else {
                LoopFrame {
                    variable: None,
                    current: 0.0,
                    step: 0.0,
                    limit: None,
                    body: strip_block(argument).to_string(),
                    body_ip: 0,
                }
            }
        };
        let body_program = Compiler::compile(&frame.body)
            .map_err(|error| VmError::new("MCOMPILE", error, line))?;

        loop {
            if frame.body_ip == 0 {
                if frame.limit.is_some_and(|end| {
                    (frame.step >= 0.0 && frame.current > end)
                        || (frame.step < 0.0 && frame.current < end)
                }) {
                    return Ok(Control::Continue);
                }
                if let Some(variable) = &frame.variable {
                    self.state
                        .vars
                        .insert(variable.clone(), Value::Number(frame.current));
                }
            }
            while frame.body_ip < body_program.instructions.len() {
                if self.slice_used >= self.slice_limit
                    && self.host.transaction_level() == 0
                    && self.inline_depth == 0
                {
                    self.state.loop_frames.insert(instruction_ip, frame);
                    self.state.ip = instruction_ip;
                    return Ok(Control::Yield);
                }
                let body_instruction = &body_program.instructions[frame.body_ip];
                frame.body_ip += 1;
                self.charge(line)?;
                match self.execute_instruction(body_instruction)? {
                    Control::Continue => {}
                    Control::Quit => return Ok(Control::Continue),
                    Control::Halt => return Ok(Control::Halt),
                    Control::Yield => {
                        // La instrucción cedió pidiendo reintento (READ sin
                        // entrada, LOCK sin adquirir): rebobinar el body_ip
                        // para no saltársela al reanudar.
                        frame.body_ip = frame.body_ip.saturating_sub(1);
                        self.state.loop_frames.insert(instruction_ip, frame);
                        self.state.ip = instruction_ip;
                        return Ok(Control::Yield);
                    }
                }
            }
            frame.body_ip = 0;
            if frame.variable.is_some() {
                if frame.step == 0.0 {
                    return Ok(Control::Continue);
                }
                frame.current += frame.step;
            }
        }
    }

    fn exec_write(&mut self, argument: &str, line: usize) -> Result<(), VmError> {
        for item in split_top_level(argument, ',') {
            let item = item.trim();
            if item.is_empty() {
                continue;
            }
            if item.chars().all(|ch| ch == '!') {
                self.state.output.push_str(&"\n".repeat(item.len()));
            } else if let Some(code) = item.strip_prefix('*') {
                let code = self.eval_expr(code, line)?.as_number() as u32;
                if let Some(character) = char::from_u32(code) {
                    self.state.output.push(character);
                }
            } else if let Some(column) = item.strip_prefix('?') {
                let target = self.eval_expr(column, line)?.as_number().max(0.0) as usize;
                let current = self.state.output.rsplit('\n').next().map_or(0, str::len);
                if target < current {
                    self.state.output.push('\n');
                    self.state.output.push_str(&" ".repeat(target));
                } else {
                    self.state.output.push_str(&" ".repeat(target - current));
                }
            } else {
                let value = self.eval_expr(item, line)?;
                self.state.output.push_str(&value.as_string());
            }
        }
        Ok(())
    }

    fn exec_read(&mut self, argument: &str, line: usize) -> Result<(), VmError> {
        let arguments = split_top_level(argument, ',');
        let target = arguments
            .last()
            .map(|value| {
                value
                    .rsplit_once(':')
                    .map_or(value.as_str(), |(_, target)| target)
                    .trim()
                    .trim_start_matches('*')
            })
            .unwrap_or_default();
        if target.is_empty() || target.starts_with('"') {
            return Ok(());
        }
        let value = self
            .host
            .read()
            .map_err(|e| VmError::new("MREAD", e, line))?;
        self.assign(target, Value::String(value), line)
    }

    fn exec_inline(&mut self, source: &str, line: usize) -> Result<(), VmError> {
        self.exec_inline_control(source, line).map(|_| ())
    }

    fn exec_inline_control(&mut self, source: &str, line: usize) -> Result<Control, VmError> {
        let program = Compiler::compile(source).map_err(|e| VmError::new("MCOMPILE", e, line))?;
        self.inline_depth += 1;
        let result = (|| {
            for instruction in &program.instructions {
                self.charge(line)?;
                let control = self.execute_instruction(instruction)?;
                if !matches!(control, Control::Continue) {
                    return Ok(control);
                }
            }
            Ok(Control::Continue)
        })();
        self.inline_depth -= 1;
        result
    }

    pub fn eval_expr(&mut self, expression: &str, line: usize) -> Result<Value, VmError> {
        let expression = trim_outer_parens(expression.trim());
        if expression.is_empty() {
            return Ok(Value::Null);
        }
        if let Some((index, operator)) = find_comparison(expression) {
            let left = self.eval_arithmetic(expression[..index].trim(), line)?;
            let right = self.eval_arithmetic(expression[index + operator.len()..].trim(), line)?;
            let result = compare_values(&left, &right, operator);
            return Ok(Value::Bool(result));
        }
        self.eval_arithmetic(expression, line)
    }

    fn eval_arithmetic(&mut self, expression: &str, line: usize) -> Result<Value, VmError> {
        let (operands, operators) = split_arithmetic(expression);
        let mut value = self.eval_atom(operands.first().map_or("", String::as_str), line)?;
        for (operator, operand) in operators.iter().zip(operands.iter().skip(1)) {
            let right = self.eval_atom(operand, line)?;
            value = apply_operator(value, right, *operator, line)?;
        }
        Ok(value)
    }

    fn eval_atom(&mut self, atom: &str, line: usize) -> Result<Value, VmError> {
        let atom = trim_outer_parens(atom.trim());
        if atom.is_empty() {
            return Ok(Value::Null);
        }
        if let Some(value) = atom.strip_prefix('+') {
            return Ok(Value::Number(self.eval_expr(value, line)?.as_number()));
        }
        if let Some(value) = atom.strip_prefix('-') {
            return Ok(Value::Number(-self.eval_expr(value, line)?.as_number()));
        }
        if let Some(value) = atom.strip_prefix('@') {
            let inner = value
                .strip_prefix('(')
                .and_then(|v| v.strip_suffix(')'))
                .unwrap_or(value);
            let resolved = self.eval_expr(inner, line)?.as_string();
            if resolved.starts_with('^') {
                let (ns, subs) = self.parse_global(&resolved, line)?;
                return self
                    .host
                    .get(&ns, &subs)
                    .map_err(|e| VmError::new("MINDIRECT", e, line))
                    .map(|v| v.unwrap_or(Value::Null));
            }
            return Ok(self
                .state
                .vars
                .get(&resolved)
                .cloned()
                .unwrap_or(Value::Null));
        }
        if atom.starts_with('$') && atom.contains('(') {
            return self.eval_function(atom, line);
        }
        if atom.starts_with('^') {
            let (ns, subs) = self.parse_global(atom, line)?;
            return self
                .host
                .get(&ns, &subs)
                .map_err(|e| VmError::new("MGET", e, line))
                .map(|v| v.unwrap_or(Value::Null));
        }
        if atom.starts_with('"') && atom.ends_with('"') && atom.len() >= 2 {
            return Ok(Value::String(atom[1..atom.len() - 1].replace("\"\"", "\"")));
        }
        if let Some(hex) = atom.strip_prefix('#') {
            if !hex.is_empty() && hex.chars().all(|ch| ch.is_ascii_hexdigit()) {
                return i64::from_str_radix(hex, 16)
                    .map(|value| Value::Number(value as f64))
                    .map_err(|e| VmError::new("MNUMBER", e.to_string(), line));
            }
        }
        if let Ok(number) = atom.parse::<f64>() {
            return Ok(Value::Number(number));
        }
        match atom.to_ascii_uppercase().as_str() {
            "$IO" => return Ok(Value::Number(self.state.current_io as f64)),
            "$ECODE" => {
                return Ok(Value::String(
                    self.state
                        .error
                        .as_ref()
                        .map_or(String::new(), |e| e.ecode.clone()),
                ))
            }
            "$ZERROR" => {
                return Ok(Value::String(
                    self.state
                        .error
                        .as_ref()
                        .map_or(String::new(), |e| e.zerror.clone()),
                ))
            }
            "$TLEVEL" => return Ok(Value::Number(self.host.transaction_level() as f64)),
            "$J" => return Ok(Value::Number(self.state.job_id as f64)),
            "$T" | "$TEST" => return Ok(Value::Number(u8::from(self.state.test) as f64)),
            "$H" | "$HOROLOG" => {
                // UTC en ambos motores: determinismo entre nodos.
                let unix = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs();
                return Ok(Value::String(format!(
                    "{},{}",
                    HOROLOG_UNIX_EPOCH_DAYS + unix / 86_400,
                    unix % 86_400
                )));
            }
            _ => {}
        }
        Ok(self.state.vars.get(atom).cloned().unwrap_or(Value::Null))
    }

    fn eval_function(&mut self, expression: &str, line: usize) -> Result<Value, VmError> {
        let open = expression
            .find('(')
            .ok_or_else(|| VmError::new("MFUNCTION", "missing (", line))?;
        let close = expression
            .rfind(')')
            .ok_or_else(|| VmError::new("MFUNCTION", "missing )", line))?;
        let name = expression[..open].to_ascii_uppercase();
        let raw_args = &expression[open + 1..close];
        let args = split_top_level(raw_args, ',');
        match name.as_str() {
            "$G" | "$GET" => {
                let first = args.first().map_or("", String::as_str);
                let value = if first.trim().starts_with('@') {
                    self.eval_atom(first, line)?
                } else if first.trim().starts_with('^') {
                    let (ns, subs) = self.parse_global(first, line)?;
                    self.host
                        .get(&ns, &subs)
                        .map_err(|e| VmError::new("MGET", e, line))?
                        .unwrap_or(Value::Null)
                } else {
                    self.eval_expr(first, line)?
                };
                if matches!(value, Value::Null) {
                    args.get(1)
                        .map_or(Ok(Value::String(String::new())), |default| {
                            self.eval_expr(default, line)
                        })
                } else {
                    Ok(value)
                }
            }
            "$D" | "$DATA" => {
                let (ns, subs) =
                    self.parse_global(args.first().map_or("", String::as_str), line)?;
                self.host
                    .data(&ns, &subs)
                    .map(|v| Value::Number(v as f64))
                    .map_err(|e| VmError::new("MDATA", e, line))
            }
            "$O" | "$ORDER" => {
                let (ns, mut subs) =
                    self.parse_global(args.first().map_or("", String::as_str), line)?;
                let current = subs.pop().and_then(|current| match &current {
                    Subscript::String(value) if value.is_empty() => None,
                    _ => Some(current),
                });
                let direction = args
                    .get(1)
                    .map(|v| self.eval_expr(v, line).map(|x| x.as_number() as i32))
                    .transpose()?
                    .unwrap_or(1);
                self.host
                    .order(&ns, &subs, current.as_ref(), direction)
                    .map(|v| v.map_or(Value::String(String::new()), |s| s.to_value()))
                    .map_err(|e| VmError::new("MORDER", e, line))
            }
            "$L" | "$LENGTH" => {
                let value = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_string();
                Ok(Value::Number(value.chars().count() as f64))
            }
            "$F" | "$FIND" => {
                let value = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_string();
                let needle = self
                    .eval_expr(args.get(1).map_or("", String::as_str), line)?
                    .as_string();
                let start = args
                    .get(2)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(1.0) as usize)
                    })
                    .transpose()?
                    .unwrap_or(1);
                let found = value
                    .get(start.saturating_sub(1)..)
                    .and_then(|tail| tail.find(&needle))
                    .map_or(0, |offset| start + offset + needle.len());
                Ok(Value::Number(found as f64))
            }
            "$P" | "$PIECE" => {
                let value = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_string();
                let delimiter = self
                    .eval_expr(args.get(1).map_or("\"\"", String::as_str), line)?
                    .as_string();
                let piece = args
                    .get(2)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(1.0) as usize)
                    })
                    .transpose()?
                    .unwrap_or(1);
                Ok(Value::String(
                    value
                        .split(&delimiter)
                        .nth(piece - 1)
                        .unwrap_or_default()
                        .to_string(),
                ))
            }
            "$E" | "$EXTRACT" => {
                let value = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_string();
                let start = args
                    .get(1)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(1.0) as usize)
                    })
                    .transpose()?
                    .unwrap_or(1);
                let end = args
                    .get(2)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(start as f64) as usize)
                    })
                    .transpose()?
                    .unwrap_or(start);
                Ok(Value::String(
                    value
                        .chars()
                        .skip(start - 1)
                        .take(end - start + 1)
                        .collect(),
                ))
            }
            "$TR" | "$TRANSLATE" => {
                let value = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_string();
                let from = self
                    .eval_expr(args.get(1).map_or("\"\"", String::as_str), line)?
                    .as_string();
                let to = self
                    .eval_expr(args.get(2).map_or("\"\"", String::as_str), line)?
                    .as_string();
                let from: Vec<char> = from.chars().collect();
                let to: Vec<char> = to.chars().collect();
                Ok(Value::String(
                    value
                        .chars()
                        .filter_map(|ch| {
                            from.iter()
                                .position(|v| *v == ch)
                                .map_or(Some(ch), |index| to.get(index).copied())
                        })
                        .collect(),
                ))
            }
            "$S" | "$SELECT" => {
                for choice in args {
                    if let Some(index) = find_top_level(&choice, ":") {
                        if self.eval_expr(choice[..index].trim(), line)?.truthy() {
                            return self.eval_expr(choice[index + 1..].trim(), line);
                        }
                    }
                }
                Ok(Value::Null)
            }
            "$A" | "$ASCII" => {
                let value = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_string();
                let position = args
                    .get(1)
                    .map(|v| self.eval_expr(v, line).map(|x| x.as_number() as i64))
                    .transpose()?
                    .unwrap_or(1);
                // Mismo contrato que func_ascii de la referencia Python:
                // posición 1-based, fuera de rango → -1.
                let code = if position < 1 {
                    -1.0
                } else {
                    value
                        .chars()
                        .nth(position as usize - 1)
                        .map_or(-1.0, |ch| ch as u32 as f64)
                };
                Ok(Value::Number(code))
            }
            "$C" | "$CHAR" => {
                let mut result = String::new();
                for argument in &args {
                    let code = self.eval_expr(argument, line)?.as_number() as i64;
                    // Referencia Python (func_char): código inválido → "?".
                    match u32::try_from(code).ok().and_then(char::from_u32) {
                        Some(ch) => result.push(ch),
                        None => result.push('?'),
                    }
                }
                Ok(Value::String(result))
            }
            "$FN" | "$FNUMBER" => {
                let number = self
                    .eval_expr(args.first().map_or("", String::as_str), line)?
                    .as_number();
                let codes = self
                    .eval_expr(args.get(1).map_or("\"\"", String::as_str), line)?
                    .as_string()
                    .to_ascii_uppercase();
                let decimals = args
                    .get(2)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(0.0) as usize)
                    })
                    .transpose()?;
                Ok(Value::String(format_fnumber(number, &codes, decimals)))
            }
            "$V" | "$VIEW" => Ok(Value::Number(0.0)),
            _ => Err(VmError::new(
                "MFUNCTION",
                format!("unsupported function {name}"),
                line,
            )),
        }
    }

    fn parse_global(
        &mut self,
        reference: &str,
        line: usize,
    ) -> Result<(String, Vec<Subscript>), VmError> {
        let reference = reference.trim();
        let raw = reference
            .strip_prefix('^')
            .ok_or_else(|| VmError::new("MGLOBAL", "global must start with ^", line))?;
        let open = raw.find('(');
        let name = open.map_or(raw, |index| &raw[..index]).trim();
        if !is_identifier(name) {
            return Err(VmError::new(
                "MGLOBAL",
                format!("invalid namespace {name}"),
                line,
            ));
        }
        let mut subs = Vec::new();
        if let Some(open) = open {
            let close = raw
                .rfind(')')
                .ok_or_else(|| VmError::new("MGLOBAL", "missing )", line))?;
            for argument in split_top_level(&raw[open + 1..close], ',') {
                let value = if argument.trim().starts_with('"')
                    || argument.trim().parse::<f64>().is_ok()
                    || self.state.vars.contains_key(argument.trim())
                    || argument.trim().starts_with('$')
                    || argument.trim().starts_with('@')
                {
                    self.eval_expr(&argument, line)?
                } else {
                    Value::String(argument.trim().to_string())
                };
                subs.push(Subscript::from_value(value));
            }
        }
        Ok((name.to_string(), subs))
    }
}

/// $FNUMBER: códigos `,` (miles) `+` (signo en positivos) `-` (suprime el
/// menos) `T` (signo al final) `P` (negativos entre paréntesis).
fn format_fnumber(value: f64, codes: &str, decimals: Option<usize>) -> String {
    let mut body = match decimals {
        // Redondeo M: mitad lejos de cero (f64::round), no banker's rounding.
        Some(digits) => {
            let factor = 10f64.powi(digits as i32);
            format!("{:.*}", digits, (value.abs() * factor).round() / factor)
        }
        None => Value::Number(value.abs()).as_string(),
    };
    // -0.4 con 0 decimales redondea a "0": sin signo.
    let negative = value < 0.0 && body.parse::<f64>().unwrap_or(0.0) != 0.0;
    if codes.contains(',') {
        let (integer, fraction) = body
            .split_once('.')
            .map_or((body.as_str(), None), |(i, f)| (i, Some(f)));
        let mut grouped = String::new();
        for (index, ch) in integer.chars().enumerate() {
            if index > 0 && (integer.len() - index) % 3 == 0 {
                grouped.push(',');
            }
            grouped.push(ch);
        }
        body = match fraction {
            Some(fraction) => format!("{grouped}.{fraction}"),
            None => grouped,
        };
    }
    if negative && codes.contains('P') {
        return format!("({body})");
    }
    let trailing = codes.contains('T');
    let mut result = String::new();
    if negative {
        if !trailing && !codes.contains('-') {
            result.push('-');
        }
    } else if !trailing && codes.contains('+') {
        result.push('+');
    }
    result.push_str(&body);
    if trailing {
        if negative {
            if !codes.contains('-') {
                result.push('-');
            }
        } else if codes.contains('+') {
            result.push('+');
        }
    }
    result
}

fn is_identifier(value: &str) -> bool {
    let mut chars = value.chars();
    chars
        .next()
        .is_some_and(|ch| ch.is_ascii_alphabetic() || ch == '%')
        && chars.all(|ch| ch.is_ascii_alphanumeric() || ch == '%' || ch == '_')
}

fn trim_outer_parens(mut value: &str) -> &str {
    loop {
        if value.starts_with('(') && value.ends_with(')') && matching_outer_parens(value) {
            value = value[1..value.len() - 1].trim();
        } else {
            return value;
        }
    }
}

fn matching_outer_parens(value: &str) -> bool {
    let mut depth = 0i32;
    let mut quoted = false;
    for (index, ch) in value.char_indices() {
        if ch == '"' {
            quoted = !quoted;
        } else if !quoted {
            if ch == '(' {
                depth += 1;
            } else if ch == ')' {
                depth -= 1;
                if depth == 0 && index + 1 != value.len() {
                    return false;
                }
            }
        }
    }
    depth == 0
}

fn split_top_level(value: &str, delimiter: char) -> Vec<String> {
    let mut result = Vec::new();
    let mut start = 0usize;
    let mut depth = 0i32;
    let mut quoted = false;
    let bytes = value.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] == b'"' {
            if quoted && i + 1 < bytes.len() && bytes[i + 1] == b'"' {
                i += 2;
                continue;
            }
            quoted = !quoted;
        } else if !quoted {
            if bytes[i] == b'(' || bytes[i] == b'{' {
                depth += 1;
            } else if bytes[i] == b')' || bytes[i] == b'}' {
                depth -= 1;
            } else if bytes[i] == delimiter as u8 && depth == 0 {
                result.push(value[start..i].trim().to_string());
                start = i + 1;
            }
        }
        i += 1;
    }
    result.push(value[start..].trim().to_string());
    result
}

fn find_top_level(value: &str, needle: &str) -> Option<usize> {
    let mut depth = 0i32;
    let mut quoted = false;
    let bytes = value.as_bytes();
    let needle = needle.as_bytes();
    let mut i = 0usize;
    while i + needle.len() <= bytes.len() {
        if bytes[i] == b'"' {
            quoted = !quoted;
            i += 1;
            continue;
        }
        if !quoted {
            match bytes[i] {
                b'(' | b'{' => depth += 1,
                b')' | b'}' => depth -= 1,
                _ => {}
            }
            if depth == 0 && &bytes[i..i + needle.len()] == needle {
                return Some(i);
            }
        }
        i += 1;
    }
    None
}

fn split_if(value: &str) -> (&str, &str, &str) {
    if let Some(open) = find_open_brace(value) {
        if let Some(close) = matching_brace(value, open) {
            let condition = value[..open].trim();
            let true_body = value[open + 1..close].trim();
            let remainder = value[close + 1..].trim();
            let false_body = remainder
                .strip_prefix("ELSE")
                .or_else(|| remainder.strip_prefix('E'))
                .map(str::trim)
                .map(strip_block)
                .unwrap_or_default();
            return (condition, true_body, false_body);
        }
    }
    for (index, ch) in value.char_indices() {
        if ch.is_whitespace() {
            let candidate = value[index..].trim_start();
            let token = candidate.split_whitespace().next().unwrap_or_default();
            let command = token
                .split(':')
                .next()
                .unwrap_or_default()
                .to_ascii_uppercase();
            if matches!(
                command.as_str(),
                "S" | "SET"
                    | "K"
                    | "KILL"
                    | "W"
                    | "WRITE"
                    | "D"
                    | "DO"
                    | "G"
                    | "GOTO"
                    | "Q"
                    | "QUIT"
                    | "H"
                    | "HALT"
                    | "L"
                    | "LOCK"
                    | "UNLOCK"
            ) {
                return (value[..index].trim(), candidate, "");
            }
        }
    }
    (value.trim(), "", "")
}

fn find_open_brace(value: &str) -> Option<usize> {
    let mut parens = 0i32;
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
            b'(' if !quoted => parens += 1,
            b')' if !quoted => parens -= 1,
            b'{' if !quoted && parens == 0 => return Some(i),
            _ => {}
        }
        i += 1;
    }
    None
}

fn matching_brace(value: &str, open: usize) -> Option<usize> {
    let mut depth = 0i32;
    let mut quoted = false;
    let bytes = value.as_bytes();
    let mut i = open;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => {
                if quoted && i + 1 < bytes.len() && bytes[i + 1] == b'"' {
                    i += 2;
                    continue;
                }
                quoted = !quoted;
            }
            b'{' if !quoted => depth += 1,
            b'}' if !quoted => {
                depth -= 1;
                if depth == 0 {
                    return Some(i);
                }
            }
            _ => {}
        }
        i += 1;
    }
    None
}

fn strip_block(value: &str) -> &str {
    let value = value.trim();
    if value.starts_with('{')
        && value.ends_with('}')
        && matching_brace(value, 0) == Some(value.len() - 1)
    {
        value[1..value.len() - 1].trim()
    } else {
        value
    }
}

fn split_for_body(value: &str) -> (&str, &str) {
    let mut depth = 0i32;
    let mut quoted = false;
    for (index, ch) in value.char_indices() {
        match ch {
            '"' => quoted = !quoted,
            '(' if !quoted => depth += 1,
            ')' if !quoted => depth -= 1,
            ch if ch.is_whitespace() && !quoted && depth == 0 => {
                return (value[..index].trim(), value[index..].trim());
            }
            _ => {}
        }
    }
    (value, "")
}

fn split_call_target(value: &str) -> (&str, &str) {
    if let Some(open) = value.find('(') {
        if value.ends_with(')') {
            return (value[..open].trim(), &value[open + 1..value.len() - 1]);
        }
    }
    (value.trim(), "")
}

fn find_comparison(value: &str) -> Option<(usize, &'static str)> {
    for operator in [">=", "<=", "!=", "=", ">", "<"] {
        if let Some(index) = find_top_level(value, operator) {
            return Some((index, operator));
        }
    }
    None
}

fn split_arithmetic(value: &str) -> (Vec<String>, Vec<char>) {
    let mut operands = Vec::new();
    let mut operators = Vec::new();
    let mut start = 0usize;
    let mut depth = 0i32;
    let mut quoted = false;
    let bytes = value.as_bytes();
    let mut i = 0usize;
    while i < bytes.len() {
        match bytes[i] {
            b'"' => quoted = !quoted,
            b'(' if !quoted => depth += 1,
            b')' if !quoted => depth -= 1,
            op @ (b'+' | b'-' | b'*' | b'/' | b'\\' | b'#' | b'_') if !quoted && depth == 0 => {
                let unary = i == start || value[start..i].trim().is_empty();
                let hex = op == b'#' && unary;
                if !unary && !hex {
                    operands.push(value[start..i].trim().to_string());
                    operators.push(op as char);
                    start = i + 1;
                }
            }
            _ => {}
        }
        i += 1;
    }
    operands.push(value[start..].trim().to_string());
    (operands, operators)
}

fn apply_operator(
    left: Value,
    right: Value,
    operator: char,
    line: usize,
) -> Result<Value, VmError> {
    if operator == '_' {
        return Ok(Value::String(left.as_string() + &right.as_string()));
    }
    let left = left.as_number();
    let right = right.as_number();
    let value = match operator {
        '+' => left + right,
        '-' => left - right,
        '*' => left * right,
        '/' => {
            if right == 0.0 {
                0.0
            } else {
                left / right
            }
        }
        '\\' => {
            if right == 0.0 {
                0.0
            } else {
                (left / right).trunc()
            }
        }
        '#' => {
            if right == 0.0 {
                0.0
            } else {
                left % right
            }
        }
        _ => {
            return Err(VmError::new(
                "MOPERATOR",
                format!("unknown operator {operator}"),
                line,
            ))
        }
    };
    Ok(Value::Number(value))
}

fn compare_values(left: &Value, right: &Value, operator: &str) -> bool {
    let numeric = matches!(left, Value::Number(_) | Value::Bool(_))
        && matches!(right, Value::Number(_) | Value::Bool(_));
    let ordering = if numeric {
        left.as_number().total_cmp(&right.as_number())
    } else {
        left.as_string().cmp(&right.as_string())
    };
    match operator {
        "=" => ordering.is_eq(),
        "!=" => !ordering.is_eq(),
        ">" => ordering.is_gt(),
        "<" => ordering.is_lt(),
        ">=" => !ordering.is_lt(),
        "<=" => !ordering.is_gt(),
        _ => false,
    }
}
