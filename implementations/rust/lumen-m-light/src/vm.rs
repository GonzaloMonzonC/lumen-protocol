use crate::compiler::{Compiler, Instruction, Opcode, Program};
use crate::compilation::CompilationManager;
use std::path::PathBuf;
use std::sync::OnceLock;
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
    /// S1: último dispositivo abierto (0 = ninguno).
    #[serde(default)]
    pub last_open_device: i64,
    /// S1: argumentos del último OPEN (ej: "GET https://...").
    #[serde(default)]
    pub last_open_args: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<VmError>,
    /// Yield requested by $AWAIT when future not ready.
    #[serde(default)]
    pub yield_requested: bool,
    /// Future ID that caused the pending yield.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub yield_future: Option<u64>,
    #[serde(default)]
    pub return_value: Option<Value>,
    /// $ZH: UNIX timestamp al crear el VM (para elapsed time)
    #[serde(default)]
    pub zh_start: f64,
    // ── Multi-fiber scheduler ───────────────────────────────────
    #[serde(default)]
    pub fibers: Vec<FiberState>,
    #[serde(default)]
    pub active_fiber: usize,

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
            last_open_device: 0,
            last_open_args: String::new(),
            error: None,
            yield_requested: false,
            yield_future: None,
            return_value: None,
            zh_start: crate::time_now_secs(),
            fibers: vec![FiberState::default()],
            active_fiber: 0,
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
/// Estado de un fiber de ejecución.
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct FiberState {
    pub id: u64,
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
    pub return_value: Option<Value>,
    #[serde(default)]
    pub yield_requested: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub yield_future: Option<u64>,
    #[serde(default)]
    pub output: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Control {
    Continue,
    Quit,
    Halt,
    Yield,
    Skip(u32),
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
    /// Valor de retorno de $$FUNC^ROUTINE() — lo setea QUIT expr
    return_value: Option<Value>,
    /// Cache de $H para el nudo lógico actual (Intersystems-style)
    horolog_cache: Option<String>,
}

// Global Compilation Manager for M→Rust JIT
static COMPILER: OnceLock<CompilationManager> = OnceLock::new();

fn get_compiler() -> &'static CompilationManager {
    COMPILER.get_or_init(|| {
        let ws = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("compiled_workspace");
        CompilationManager::new(&ws)
    })
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
            return_value: None,
            horolog_cache: None,
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
            return_value: None,
            horolog_cache: None,
        })
    }

    pub fn run(&mut self) -> Execution {
        self.run_slice(self.state.gas_limit)
    }

    

    /// Guarda el estado del fiber activo en la lista de fibers.
    fn save_fiber(&mut self) {
        let i = self.state.active_fiber;
        if i < self.state.fibers.len() {
            self.state.fibers[i].ip = self.state.ip;
            self.state.fibers[i].stack = std::mem::take(&mut self.state.stack);
            self.state.fibers[i].vars = std::mem::take(&mut self.state.vars);
            self.state.fibers[i].call_stack = std::mem::take(&mut self.state.call_stack);
            self.state.fibers[i].loop_frames = std::mem::take(&mut self.state.loop_frames);
            self.state.fibers[i].local_scopes = std::mem::take(&mut self.state.local_scopes);
            self.state.fibers[i].argument_scopes = std::mem::take(&mut self.state.argument_scopes);
            self.state.fibers[i].return_value = self.state.return_value.take();
            self.state.fibers[i].yield_requested = self.state.yield_requested;
            self.state.fibers[i].yield_future = self.state.yield_future;
            self.state.fibers[i].output = std::mem::take(&mut self.state.output);
        }
    }

    /// Carga el estado de un fiber en los campos planos de VmState.
    fn load_fiber(&mut self, index: usize) {
        if index < self.state.fibers.len() {
            let f = &self.state.fibers[index];
            self.state.ip = f.ip;
            self.state.stack = f.stack.clone();
            self.state.vars = f.vars.clone();
            self.state.call_stack = f.call_stack.clone();
            self.state.loop_frames = f.loop_frames.clone();
            self.state.local_scopes = f.local_scopes.clone();
            self.state.argument_scopes = f.argument_scopes.clone();
            self.state.return_value = f.return_value.clone();
            self.state.yield_requested = f.yield_requested;
            self.state.yield_future = f.yield_future;
            self.state.output = f.output.clone();
        }
        self.state.active_fiber = index;
    }

    /// Cambia al siguiente fiber listo. Si solo hay uno, es no-op.
    fn switch_fiber(&mut self) {
        if self.state.fibers.len() <= 1 { return; }
        self.save_fiber();
        let n = self.state.fibers.len();
        for _ in 0..n {
            let next = (self.state.active_fiber + 1) % n;
            let f = &self.state.fibers[next];
            let frozen = f.yield_future.is_some() || f.yield_requested || f.ip >= self.program.instructions.len();
            if !frozen {
                self.load_fiber(next);
                return;
            }
        }
        self.load_fiber(self.state.active_fiber);
    }

pub fn run_slice(&mut self, gas: u64) -> Execution {
        self.switch_fiber();

        self.switch_fiber();
        self.slice_used = 0;
        self.slice_limit = gas.max(1);
        while self.state.ip < self.program.instructions.len() && !self.state.halted {
            if self.slice_used >= self.slice_limit && self.host.transaction_level() == 0 {
                return Execution::Yielded;
            }
            let instruction = self.program.instructions[self.state.ip].clone();
            self.state.ip += 1;
            if let Err(error) = self.charge(instruction.line) {
                if error.zerror == "GAS_EXHAUSTED" {
                    self.rollback_open_transactions();
                    // Save PC (already at next instruction), yield gracefully
                    return Execution::Yielded;
                }
                self.rollback_open_transactions();
                self.state.error = Some(error);
                self.state.halted = true;
                return Execution::Error;
            }
            match self.execute_instruction(&instruction) {
                Ok(Control::Continue) => {
                    if self.state.yield_requested {
                        self.state.ip -= 1;
                        self.state.yield_requested = false;
                        return Execution::Yielded;
                    }
                }
                Ok(Control::Skip(n)) => self.state.ip += n as usize,
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
            Opcode::Else => {
                if self.state.test {
                    // IF was true — skip the ELSE body (1 instruction)
                    return Ok(Control::Skip(1));
                }
                self.exec_inline(&instruction.argument, instruction.line)?;
            }
            Opcode::For => return self.exec_for(&instruction.argument, instruction.line),
            Opcode::Quit => {
                let argument = instruction.argument.trim();
                if argument.is_empty() {
                    return Ok(Control::Quit);
                }
                let value = self.eval_expr(argument, instruction.line)?;
                self.state.stack.push(value.clone());
                self.return_value = Some(value);
                return Ok(Control::Quit);
            }
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
            Opcode::Open => {
                // Parse device number: "8:args..." or just "8"
                let arg = &instruction.argument;
                self.state.last_open_args = arg.clone();
                if let Some(colon) = arg.find(':') {
                    if let Ok(dev) = arg[..colon].trim().parse::<i64>() {
                        self.state.current_io = dev;
                        self.state.last_open_device = dev;
                    }
                } else if let Ok(dev) = arg.trim().parse::<i64>() {
                    self.state.current_io = dev;
                    self.state.last_open_device = dev;
                }
            }
            Opcode::Close => {}
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
        let argument = argument.trim_start();
        // find first space outside parens/quotes (smart split for strings)
        let target = {
            let mut depth = 0i32;
            let mut quoted = false;
            let mut split_at = argument.len();
            for (j, c) in argument.char_indices() {
                match c {
                    '"' => quoted = !quoted,
                    '(' | '{' if !quoted => depth += 1,
                    ')' | '}' if !quoted => depth -= 1,
                    ' ' if depth == 0 && !quoted => { split_at = j; break; }
                    _ => {}
                }
            }
            &argument[..split_at]
        };
        let (target_name, raw_arguments) = split_call_target(target);
        // Empty target = block marker DO (IF cond DO), just continue
        if target_name.is_empty() {
            return Ok(Control::Continue);
        }
        // Skip dot block markers (DO .. SET → DO SET, DO . SET → DO SET)
        if !target_name.is_empty() && target_name.chars().all(|c| c == '.') {
            let rest = &argument[target.len()..].trim_start();
            if !rest.is_empty() {
                return self.exec_do(rest, line);
            }
            return Ok(Control::Continue);
        }
        // DO followed by another M command — could be block marker (skip) or same-line continuation
        if is_command_name(target_name) {
            let original_arg = argument.trim();
            if original_arg.len() > target_name.len() {
                let after = &original_arg[target_name.len()..].trim();
                if !after.is_empty() {
                    return self.exec_inline_control(original_arg, line);
                }
            }
            return Ok(Control::Continue);
        }
        if target_name.starts_with('^') {
            let name = target_name.trim_start_matches('^').trim();
            let source = self
                .host
                .routine(name)
                .map_err(|e| VmError::new("MROUTINE", e, line))?
                .ok_or_else(|| VmError::new("MROUTINE", format!("unknown routine {name}"), line))?;
            
            // Try compiled version first — BYPASS real del intérprete
            let compiler = get_compiler();
            if let Some(compiled_fn) = compiler.get_compiled_fn(name) {
                match compiled_fn() {
                    Ok(_val) => {
                        return Ok(Control::Continue);
                    }
                    Err(e) => {
                        eprintln!("JIT: compiled '{}' returned error: {}, falling back", name, e);
                    }
                }
            }
            // Not compiled yet — track calls to trigger compilation
            compiler.track_call(name, &source);
            
            let arguments = split_top_level(raw_arguments, ',')
                .into_iter()
                .filter(|value| !value.is_empty())
                .map(|value| self.eval_expr(&value, line))
                .collect::<Result<Vec<_>, _>>()?;
            self.bind_arguments(arguments);
            let scope_base = self.state.local_scopes.len();
            let result = self.exec_inline_control(&source, line);
            self.restore_local_scopes_to(scope_base);
            self.restore_arguments();
            let control = result?;
            return Ok(match control {
                Control::Halt => Control::Halt,
                Control::Skip(n) => Control::Skip(n),
                _ => Control::Continue,
            });
        } else if let Some(caret) = target_name.find('^') {
            // DO LABEL^ROUTINE(args) — load routine from host, find label
            let inner_label = target_name[..caret].trim().to_ascii_uppercase();
            let routine_name = target_name[caret + 1..].trim();
            let source = self.host.routine(routine_name)
                .map_err(|e| VmError::new("MROUTINE", e, line))?
                .ok_or_else(|| VmError::new("MROUTINE", format!("unknown routine {routine_name}"), line))?;
            let program = Compiler::compile(&source)
                .map_err(|e| VmError::new("MCOMPILE", e, line))?;
            let start_ip = *program.labels.get(&inner_label)
                .ok_or_else(|| VmError::new("MLABEL", format!("unknown label {inner_label} in {routine_name}"), line))?;
            // Handle .ref args (pass-by-reference)
            let formals = parse_formal_params(&source, &inner_label).unwrap_or_default();
            let mut refs: Vec<(String, String)> = Vec::new();
            let raw_args_list = split_top_level(raw_arguments, ',')
                .into_iter()
                .filter(|v| !v.is_empty())
                .collect::<Vec<_>>();
            let mut evaluated = Vec::new();
            for (i, raw) in raw_args_list.iter().enumerate() {
                let trimmed = raw.trim();
                let param_name = formals.get(i).cloned().unwrap_or_default();
                if trimmed.starts_with('.') && !param_name.is_empty() {
                    let src_var = trimmed.trim_start_matches('.').trim().to_string();
                    if is_identifier(&src_var) {
                        let prefix = format!("{}[", src_var);
                        let collected: Vec<(String, Value)> = self.state.vars.iter()
                            .filter(|(k, _)| k.starts_with(&prefix))
                            .map(|(k, v)| (k.clone(), v.clone()))
                            .collect();
                        for (key, val) in &collected {
                            let suffix = key.trim_start_matches(&prefix);
                            self.state.vars.insert(format!("{}[{}", param_name, suffix), val.clone());
                        }
                        refs.push((src_var, param_name));
                        evaluated.push(Value::Null);
                        continue;
                    }
                } else if trimmed.starts_with('.') && param_name.is_empty() {
                    // .ref without formal params — array already accessible via flattening
                    // Just push placeholder, no rename needed
                    evaluated.push(Value::Null);
                    continue;
                }
                evaluated.push(self.eval_expr(raw, line)?);
            }
            for (i, pname) in formals.iter().enumerate() {
                let trimmed = raw_args_list.get(i).map(|a| a.trim()).unwrap_or("");
                if !trimmed.starts_with('.') {
                    if let Some(val) = evaluated.get(i) {
                        self.state.vars.insert(pname.clone(), val.clone());
                    }
                }
            }
            let scope_base = self.state.local_scopes.len();
            self.bind_arguments(evaluated);
            self.inline_depth += 1;
            let mut i = start_ip;
            while i < program.instructions.len() {
                self.charge(line)?;
                let ctrl = self.execute_instruction(&program.instructions[i])?;
                match ctrl {
                    Control::Continue => i += 1,
                    Control::Skip(n) => i += 1 + n as usize,
                    Control::Quit | Control::Halt | Control::Yield => break,
                }
            }
            self.inline_depth -= 1;
            for (src_var, param_name) in &refs {
                let prefix = format!("{}[", param_name);
                let collected: Vec<(String, Value)> = self.state.vars.iter()
                    .filter(|(k, _)| k.starts_with(&prefix))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect();
                for (key, val) in &collected {
                    let suffix = key.trim_start_matches(&prefix);
                    self.state.vars.insert(format!("{}[{}", src_var, suffix), val.clone());
                }
                // Copy scalar value: SET modes=i → all=i
                if let Some(scalar) = self.state.vars.get(param_name).cloned() {
                    self.state.vars.insert(src_var.clone(), scalar);
                }
            }
            self.restore_local_scopes_to(scope_base);
            self.restore_arguments();
        } else {
            // D LABEL(args) — local DO with optional .ref pass-by-reference
            let label_upper = target_name.trim().to_ascii_uppercase();
            let source_local = self.program.source.clone();
            let formals = parse_formal_params(&source_local, &label_upper).unwrap_or_default();
            
            let mut refs: Vec<(String, String)> = Vec::new();
            let raw_args_list = split_top_level(raw_arguments, ',')
                .into_iter()
                .filter(|v| !v.is_empty())
                .collect::<Vec<_>>();
            let mut evaluated = Vec::new();
            
            for (i, raw) in raw_args_list.iter().enumerate() {
                let trimmed = raw.trim();
                let param_name = formals.get(i).cloned().unwrap_or_default();
                if trimmed.starts_with('.') && !param_name.is_empty() {
                    let src_var = trimmed.trim_start_matches('.').trim().to_string();
                    if is_identifier(&src_var) {
                        // Copy array from caller var to callee param
                        let prefix = format!("{}[", src_var);
                        let collected: Vec<(String, Value)> = self.state.vars.iter()
                            .filter(|(k, _)| k.starts_with(&prefix))
                            .map(|(k, v)| (k.clone(), v.clone()))
                            .collect();
                        for (key, val) in &collected {
                            let suffix = key.trim_start_matches(&prefix);
                            self.state.vars.insert(format!("{}[{}", param_name, suffix), val.clone());
                        }
                        refs.push((src_var, param_name));
                        evaluated.push(Value::Null);
                        continue;
                    }
                }
                evaluated.push(self.eval_expr(raw, line)?);
            }
            
            // Bind non-.ref params as $1, $2, ...
            for (i, pname) in formals.iter().enumerate() {
                let trimmed = raw_args_list.get(i).map(|a| a.trim()).unwrap_or("");
                if !trimmed.starts_with('.') {
                    if let Some(val) = evaluated.get(i) {
                        self.state.vars.insert(pname.clone(), val.clone());
                    }
                }
            }
            self.bind_arguments(evaluated);
            
            // Local label jump
            let destination = self.label_ip(target_name, line)?;
            let saved_ip = self.state.ip;
            self.state.call_stack.push(self.state.ip);
            self.state.ip = destination;
            
            // Execute up to label
            while self.state.ip < self.program.instructions.len() && !self.state.halted {
                let instr = self.program.instructions[self.state.ip].clone();
                let ctrl = self.execute_instruction(&instr)?;
                match ctrl {
                    Control::Continue => self.state.ip += 1,
                    Control::Skip(n) => self.state.ip += 1 + n as usize,
                    Control::Quit | Control::Halt | Control::Yield => break,
                }
            }
            self.state.ip = saved_ip;
            
            // Write back .ref vars
            for (src_var, param_name) in &refs {
                let prefix = format!("{}[", param_name);
                let collected: Vec<(String, Value)> = self.state.vars.iter()
                    .filter(|(k, _)| k.starts_with(&prefix))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect();
                for (key, val) in &collected {
                    let suffix = key.trim_start_matches(&prefix);
                    self.state.vars.insert(format!("{}[{}", src_var, suffix), val.clone());
                }
                if let Some(scalar) = self.state.vars.get(param_name).cloned() {
                    self.state.vars.insert(src_var.clone(), scalar);
                }
            }
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
        let stripped = reference.trim_start_matches('+').trim_start_matches('-');
        let resolved = self.resolve_target(stripped, line)?;
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
        } else if let Some(flat) = flatten_local_sub(&resolved) {
            // Evaluate subscript variables: modes(i) with i=2 → modes[2]
            let evaluated = if let Some(bracket) = flat.find('[') {
                let base = &flat[..bracket];
                let inner = &flat[bracket+1..flat.len()-1];
                let subscript = if is_identifier(inner) && self.state.vars.contains_key(inner) {
                    let val = self.eval_expr(inner, line)?;
                    val.as_string()
                } else {
                    inner.to_string()
                };
                format!("{}[{}]", base, subscript)
            } else {
                flat.clone()
            };
            self.state.vars.insert(evaluated, value);
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
        // Check for \x01-separated bodies (IF DO with ELSE DO compiled by compiler)
        if let Some(sep1) = argument.find('\x01') {
            let condition = &argument[..sep1];
            let rest = &argument[sep1 + 1..];
            let (true_body, false_body) = if let Some(sep2) = rest.find('\x01') {
                (&rest[..sep2], &rest[sep2 + 1..])
            } else {
                (rest, "")
            };
            let truthy = self.eval_expr(condition, line)?.truthy();
            self.state.test = truthy;
            let selected = if truthy { true_body } else { false_body };
            // Strip leading DO/D marker from inline IF body
            let selected = {
                let s = selected.trim_start();
                let upper = s.to_uppercase();
                if upper.starts_with("DO ") || upper.starts_with("D ") || upper == "DO" || upper == "D" {
                    let after = &s[s.find(char::is_whitespace).unwrap_or(s.len())..].trim_start();
                    if after.is_empty() { "" } else { after }
                } else { s }
            };
            if !selected.is_empty() {
                return self.exec_inline_control(selected, line);
            }
            return Ok(Control::Continue);
        }
        // Legacy format: use split_if
        let (condition, true_body, false_body) = split_if(argument);
        let truthy = self.eval_expr(condition, line)?.truthy();
        self.state.test = truthy;
        let selected = if truthy { true_body } else { false_body };
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
            #[cfg(feature = "debug_for")]
            eprintln!("[exec_for] argument={argument:?} → spec={specification:?} body={raw_body:?}");
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
                    Control::Skip(n) => frame.body_ip += n as usize,
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
        // Join all lines into one so FOR consumes remainder across newlines
        let flat = source.lines()
            .map(|l| l.trim())
            .filter(|l| !l.is_empty())
            .collect::<Vec<_>>()
            .join(" ");
        // Remove DO block markers before M commands (FOR DO → FOR continuation)
        let commands = ["S ", "SET ", "I ", "IF ", "F ", "FOR ", "D ", "DO ",
                        "K ", "KILL ", "Q ", "QUIT ", "N ", "NEW ",
                        "W ", "WRITE ", "ZWRITE ", "ZW ", "ZP ", "ZPRINT "];
        let mut flat = flat;
        for cmd in &commands {
            let pattern = format!(" DO {}", cmd.trim());
            let replacement = format!(" {}", cmd.trim());
            flat = flat.replace(&pattern, &replacement);
            let pattern = format!(" D {}", cmd.trim());
            flat = flat.replace(&pattern, &replacement);
        }
        let program = Compiler::compile(&flat).map_err(|e| VmError::new("MCOMPILE", e, line))?;
        self.inline_depth += 1;
        let result = (|| {
            for instruction in &program.instructions {
                self.charge(line)?;
                let control = self.execute_instruction(instruction)?;
                if !matches!(control, Control::Continue) {
                    // Skip must propagate too
                    if let Control::Skip(_) = control {}
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
        if let Some(value) = atom.strip_prefix("'") {
            let v = self.eval_expr(value, line)?;
            return Ok(Value::Bool(v.as_number() == 0.0));
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
        // $$FUNC^ROUTINE without parentheses — route to eval_function as well
        if atom.starts_with("$$") && !atom.contains('(') {
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
                // Cache por nudo lógico: Intersystems-style, $H no cambia intra-call
                if let Some(ref cached) = self.horolog_cache {
                    return Ok(Value::String(cached.clone()));
                }
                let unix = crate::time_now_secs() as u64;
                let result = format!(
                    "{},{}",
                    HOROLOG_UNIX_EPOCH_DAYS + unix / 86_400,
                    unix % 86_400
                );
                self.horolog_cache = Some(result.clone());
                return Ok(Value::String(result));
            }
            "$ZH" => {
                let now = crate::time_now_secs();
                return Ok(Value::Number(now - self.state.zh_start));
            }
            _ => {}
        }
        // Try direct key, then flattened local array key (e.g., m("type") → m["type"])
        if let Some(value) = self.state.vars.get(atom).cloned() {
            return Ok(value);
        }
        if let Some(flat) = flatten_local_sub(atom) {
            if let Some(value) = self.state.vars.get(&flat).cloned() {
                return Ok(value);
            }
        }
        Err(VmError::new("MUNDEF", &format!("undefined variable: {atom}"), line))
    }

    fn eval_function(&mut self, expression: &str, line: usize) -> Result<Value, VmError> {
        let (name, raw_args) = if let Some(open) = expression.find('(') {
            let close = expression.rfind(')')
                .ok_or_else(|| VmError::new("MFUNCTION", "missing )", line))?;
            (expression[..open].to_ascii_uppercase(),
             expression[open + 1..close].to_string())
        } else {
            // No parens: $$FUNC^ROUTINE or $$FUNC
            (expression.to_ascii_uppercase(), String::new())
        };
        let args = if raw_args.is_empty() {
            Vec::new()
        } else {
            split_top_level(&raw_args, ',')
        };
        match name.as_str() {
            "$I" | "$INCREMENT" => {
                let var_ref = args.first().map_or("", String::as_str).trim().to_string();
                if var_ref.is_empty() {
                    return Err(VmError::new("MINCR", "empty argument", line));
                }
                // Read current value (existing or 0)
                let current = if var_ref.starts_with('^') {
                    let (ns, subs) = self.parse_global(&var_ref, line)?;
                    self.host
                        .get(&ns, &subs)
                        .map_err(|e| VmError::new("MGET", e, line))?
                        .unwrap_or(Value::Number(0.0))
                } else {
                    self.state.vars.get(&var_ref).cloned()
                        .or_else(|| flatten_local_sub(&var_ref).and_then(|k| self.state.vars.get(&k).cloned()))
                        .unwrap_or(Value::Number(0.0))
                };
                let new_value = Value::Number(current.as_number() + 1.0);
                self.assign(&var_ref, new_value.clone(), line)?;
                Ok(new_value)
            }
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
                    // Local variable: look up directly or via flattened key
                    let key = first.trim();
                    let val = self.state.vars.get(key).cloned()
                        .or_else(|| flatten_local_sub(key).and_then(|k| self.state.vars.get(&k).cloned()))
                        .unwrap_or(Value::Null);
                    val
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
                let first_arg = args.first().map_or("", String::as_str).trim();
                if first_arg.starts_with('^') {
                    let (ns, subs) = self.parse_global(first_arg, line)?;
                    self.host.data(&ns, &subs)
                        .map(|v| Value::Number(v as f64))
                        .map_err(|e| VmError::new("MDATA", e, line))
                } else if first_arg.starts_with('$') {
                    // $DATA of a function result or special var — not meaningful, return 0
                    Ok(Value::Number(0.0))
                } else {
                    // Local variable or array: hierarchical $DATA
                    let key_first = first_arg.trim();
                    let has_value = self.state.vars.get(key_first).cloned()
                        .or_else(|| flatten_local_sub(key_first).and_then(|k| self.state.vars.get(&k).cloned()));
                    // Check for children (subordinate keys)
                    let flat_prefix = flatten_local_sub(key_first)
                        .unwrap_or_else(|| format!("{}[", key_first));
                    let has_children = self.state.vars.keys()
                        .any(|k| k != &flat_prefix && k.starts_with(&flat_prefix[..flat_prefix.len().saturating_sub(1)]));
                    // Actually determine: for flattened key like def["name"], check if there's a parent
                    Ok(if has_value.is_some() {
                        if has_children { Value::Number(11.0) } else { Value::Number(1.0) }
                    } else {
                        if has_children { Value::Number(10.0) } else { Value::Number(0.0) }
                    })
                }
            }
            "$O" | "$ORDER" => {
                let raw_first = args.first().map_or("", String::as_str).trim();
                if raw_first.starts_with('^') {
                    let (ns, mut subs) = self.parse_global(raw_first, line)?;
                    // En M canónico, $O(^G("")) significa "primer subíndice" (current
                    // vacío). Un String("") como current nunca supera a un Number en el
                    // orden canónico (números < strings), así que devolvería siempre el
                    // primer subíndice string y NUNCA los numéricos. Tratamos el vacío
                    // como ausencia de current.
                    let current = subs.pop().filter(|s| !matches!(s, crate::value::Subscript::String(v) if v.is_empty()));
                    let direction = args.get(1)
                        .map(|v| self.eval_expr(v, line).map(|x| x.as_number() as i32))
                        .transpose()?
                        .unwrap_or(1);
                    self.host.order(&ns, &subs, current.as_ref(), direction)
                        .map(|v| v.map_or(Value::String(String::new()), |s| s.to_value()))
                        .map_err(|e| VmError::new("MORDER", e, line))
                } else {
                    // Local array $ORDER
                    let direction = args.get(1)
                        .map(|v| self.eval_expr(v, line).map(|x| x.as_number() as i32))
                        .transpose()?
                        .unwrap_or(1);
                    let flat_key = flatten_local_sub(raw_first)
                        .unwrap_or_else(|| raw_first.to_string());
                    let brack = flat_key.find('[').map(|i| i + 1).unwrap_or(0);
                    let prefix = if brack > 0 { format!("{}[", &flat_key[..brack-1]) } else { format!("{}[", flat_key) };
                    let current_sub: Option<String> = if brack > 0 {
                        let inner = &flat_key[brack..];
                        Some(if inner.ends_with(']') { inner[..inner.len()-1].to_string() } else { inner.to_string() })
                    } else {
                        None
                    };
                    let mut matched: Vec<String> = self.state.vars.keys()
                        .filter(|k| k.starts_with(&prefix))
                        .map(|k| k[prefix.len()..].to_string())
                        .filter(|suffix| suffix.ends_with(']'))
                        .map(|suffix| suffix[..suffix.len()-1].to_string())
                        .collect();
                    matched.sort();
                    let result: Option<String> = if direction > 0 {
                        if let Some(ref cur) = current_sub {
                            matched.into_iter().find(|k| k > cur)
                        } else {
                            matched.into_iter().next()
                        }
                    } else {
                        if let Some(ref cur) = current_sub {
                            matched.into_iter().rev().find(|k| k < cur)
                        } else {
                            matched.into_iter().rev().next()
                        }
                    };
                    Ok(match result {
                        Some(s) => Value::String(s),
                        None => Value::String(String::new()),
                    })
                }
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
                if delimiter.is_empty() {
                    // M estándar: $P con delimitador vacío no devuelve piezas
                    return Ok(Value::String(String::new()));
                }
                let piece = args
                    .get(2)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(1.0) as usize)
                    })
                    .transpose()?
                    .unwrap_or(1);
                // M estándar: $P(string, delim, from, to) → piezas from..to
                // unidas con el delimitador. Sin `to`, devuelve una sola pieza.
                let end = args
                    .get(3)
                    .map(|v| {
                        self.eval_expr(v, line)
                            .map(|x| x.as_number().max(piece as f64) as usize)
                    })
                    .transpose()?;
                let pieces: Vec<&str> = value.split(&delimiter).collect();
                let n = pieces.len();
                let from = piece.min(n);
                let to = end.map_or(from, |e| e.min(n));
                if from == 0 || from > to {
                    return Ok(Value::String(String::new()));
                }
                let joined = pieces[from - 1..to].join(&delimiter);
                Ok(Value::String(joined))
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
            "$J" | "$JUSTIFY" => {
                let value = self.eval_expr(args.first().map_or("", String::as_str), line)?;
                let length = self.eval_expr(args.get(1).map_or("0", String::as_str), line)?.as_number() as usize;
                if args.len() >= 3 {
                    // With decimal places: $J(number, length, decimal)
                    let decimal = self.eval_expr(args.get(2).map_or("0", String::as_str), line)?.as_number() as usize;
                    let num = value.as_number();
                    let formatted = format!("{:.*}", decimal, num);
                    Ok(Value::String(format!("{:>width$}", formatted, width = length)))
                } else {
                    // String/right-justify: $J(value, length)
                    let string = value.as_string();
                    Ok(Value::String(format!("{:>width$}", string, width = length)))
                }
            }
            "$V" | "$VIEW" => Ok(Value::Number(0.0)),
            // ── LLM Device functions ──────────────────────────
            "$DEVICE" => {
                let path = self.eval_expr(args.get(0).map_or("", String::as_str), line)?.as_string();
                let call_args: Vec<Value> = args[1..].iter().map(|a| self.eval_expr(a, line)).collect::<Result<_, _>>()?;
                let (dev, act) = path.split_once(':').unwrap_or((&path, "call"));
                match (dev, act) {
                    ("llm", "call") | ("llm", "fork") => {
                        let prompt = call_args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let system = call_args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        let provider = call_args.get(2).map(|v| v.as_string()).unwrap_or_else(|| "deepseek".to_string());
                        let model = call_args.get(3).map(|v| v.as_string()).unwrap_or_else(|| "deepseek-v4-flash".to_string());
                        // Reuse stored future ID if resuming from a yield
                        let id = if act == "call" {
                            if let Some(fid) = self.state.yield_future.take() {
                                fid
                            } else {
                                self.host.llm_fork(&provider, &model, &prompt, &system)
                                    .map_err(|e| VmError::new("MLLM", e, line))?
                            }
                        } else {
                            self.host.llm_fork(&provider, &model, &prompt, &system)
                                .map_err(|e| VmError::new("MLLM", e, line))?
                        };
                        if act == "fork" {
                            Ok(Value::Number(id as f64))
                        } else {
                            match self.host.llm_poll(id).map_err(|e| VmError::new("MLLM", e, line))? {
                                Some(r) => Ok(Value::String(r)),
                                None => {
                                    self.state.yield_requested = true;
                                    self.state.yield_future = Some(id);
                                    Ok(Value::Null)
                                }
                            }
                        }
                    }
                    ("llm", "await") => {
                        let id = call_args.get(0).map(|v| v.as_number() as u64).unwrap_or(0);
                        match self.host.llm_poll(id).map_err(|e| VmError::new("MLLM", e, line))? {
                            Some(r) => Ok(Value::String(r)),
                            None => {
                                self.state.yield_requested = true;
                                self.state.yield_future = Some(id);
                                Ok(Value::Null)
                            }
                        }
                    }
                    ("llm", "cancel") => {
                        let id = call_args.get(0).map(|v| v.as_number() as u64).unwrap_or(0);
                        Ok(Value::Bool(self.host.llm_cancel(id).unwrap_or(false)))
                    }
                    ("llm", "all") => {
                        let ids_str = call_args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let ids: Vec<u64> = ids_str.split(',').filter_map(|s| s.trim().parse().ok()).collect();
                        let mut results = Vec::new();
                        for &id in &ids {
                            match self.host.llm_poll(id).map_err(|e| VmError::new("MLLM", e, line))? {
                                Some(r) => results.push(r),
                                None => {
                                    self.state.yield_requested = true;
                                    return Ok(Value::Null);
                                }
                            }
                        }
                        Ok(Value::String(results.join("|")))
                    }
                    ("llm", "chain") => {
                        let parent_id = call_args.get(0).map(|v| v.as_number() as u64).unwrap_or(0);
                        let prompt = call_args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        let system = call_args.get(2).map(|v| v.as_string()).unwrap_or_default();
                        let provider = call_args.get(3).map(|v| v.as_string()).unwrap_or_else(|| "deepseek".to_string());
                        let model = call_args.get(4).map(|v| v.as_string()).unwrap_or_else(|| "deepseek-v4-flash".to_string());
                        let id = self.host.llm_chain(parent_id, &provider, &model, &prompt, &system)
                            .map_err(|e| VmError::new("MLLM", e, line))?;
                        Ok(Value::Number(id as f64))
                    }
                    _ => {
                        // Sync device (HTTP, etc.)
                        self.host.device_call(dev, act, &call_args)
                            .map_err(|e| VmError::new("MDEV", e, line))
                    }
                }
            }
            "$LLM" => {
                let prompt = self.eval_expr(args.get(0).map_or("", String::as_str), line)?.as_string();
                let system = args.get(1).map_or("".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let provider = args.get(2).map_or("deepseek".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let model = args.get(3).map_or("deepseek-v4-flash".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                // Reuse future ID if resuming from a yield
                let id = if let Some(fid) = self.state.yield_future.take() {
                    fid
                } else {
                    self.host.llm_fork(&provider, &model, &prompt, &system)
                        .map_err(|e| VmError::new("MLLM", e, line))?
                };
                match self.host.llm_poll(id).map_err(|e| VmError::new("MLLM", e, line))? {
                    Some(result) => Ok(Value::String(result)),
                    None => {
                        self.state.yield_requested = true;
                        self.state.yield_future = Some(id);
                        Ok(Value::Null)
                    }
                }
            }
            "$FORK" => {
                let prompt = self.eval_expr(args.get(0).map_or("", String::as_str), line)?.as_string();
                let system = args.get(1).map_or("".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let provider = args.get(2).map_or("deepseek".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let model = args.get(3).map_or("deepseek-v4-flash".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let id = self.host.llm_fork(&provider, &model, &prompt, &system)
                    .map_err(|e| VmError::new("MLLM", e, line))?;
                Ok(Value::Number(id as f64))
            }
            "$AWAIT" => {
                let id = self.eval_expr(args.get(0).map_or("0", String::as_str), line)?.as_number() as u64;
                match self.host.llm_poll(id).map_err(|e| VmError::new("MLLM", e, line))? {
                    Some(result) => Ok(Value::String(result)),
                    None => {
                        self.state.yield_requested = true;
                        self.state.yield_future = Some(id);
                        Ok(Value::Null)
                    }
                }
            }
            
            "$FIBER" => {
                let action = self.eval_expr(args.get(0).map_or("", String::as_str), line)?.as_string();
                match action.as_str() {
                    "spawn" => {
                        let mut new_f = FiberState::default();
                        new_f.id = self.state.fibers.len() as u64;
                        new_f.ip = self.state.ip;
                        new_f.vars = self.state.vars.clone();
                        let id = new_f.id;
                        self.state.fibers.push(new_f);
                        Ok(Value::Number(id as f64))
                    }
                    "bg" => {
                        let source = self.eval_expr(args.get(1).map_or("", String::as_str), line)?.as_string();
                        let entries = self.host.entries().unwrap_or_default();
                        let routines = self.host.routines_list().unwrap_or_default();
                        let keys = self.host.llm_api_keys().unwrap_or_default();
                        let id = self.host.fiber_bg_spawn(&source, &entries, &routines, &keys)
                            .map_err(|e| VmError::new("MFBG", e, line))?;
                        Ok(Value::Number(id as f64))
                    }
                    "join" => {
                        let id = self.eval_expr(args.get(1).map_or("0", String::as_str), line)?.as_number() as u64;
                        if id == 0 {
                            return Err(VmError::new("MFBG", "invalid fiber_id: 0", line));
                        }
                        match self.host.fiber_bg_poll(id).map_err(|e| VmError::new("MFBG", e, line))? {
                            Some(result) => Ok(Value::String(result)),
                            None => {
                                // Check if fiber exists before yielding
                                let exists = self.host.fiber_bg_exists(id).map_err(|e| VmError::new("MFBG", e, line))?;
                                if !exists {
                                    return Err(VmError::new("MFBG", &format!("fiber {id} not found"), line));
                                }
                                self.state.yield_requested = true;
                                self.state.yield_future = Some(id);
                                Ok(Value::Null)
                            }
                        }
                    }
                    "count" => Ok(Value::Number(self.state.fibers.len() as f64)),
                    "me" => Ok(Value::Number(self.state.active_fiber as f64)),
                    _ => Ok(Value::Null),
                }
            }
            "$YIELD" => {
                self.state.yield_requested = true;
                Ok(Value::Null)
            }
"$CHAIN" => {
                let parent = self.eval_expr(args.get(0).map_or("0", String::as_str), line)?.as_number() as u64;
                let prompt = self.eval_expr(args.get(1).map_or("", String::as_str), line)?.as_string();
                let system = args.get(2).map_or("".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let provider = args.get(3).map_or("deepseek".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let model = args.get(4).map_or("deepseek-v4-flash".to_string(), |a| self.eval_expr(a, line).map(|v| v.as_string()).unwrap_or_default());
                let id = self.host.llm_chain(parent, &provider, &model, &prompt, &system)
                    .map_err(|e| VmError::new("MLLM", e, line))?;
                Ok(Value::Number(id as f64))
            }
            "$CANCEL" => {
                let id = self.eval_expr(args.get(0).map_or("0", String::as_str), line)?.as_number() as u64;
                let ok = self.host.llm_cancel(id)
                    .map_err(|e| VmError::new("MLLM", e, line))?;
                Ok(Value::Bool(ok))
            }
            "$ALL" => {
                let ids: Vec<u64> = if args.len() == 1 {
                    let list = self.eval_expr(&args[0], line)?.as_string();
                    list.split(',').filter_map(|s| s.trim().parse::<u64>().ok()).collect()
                } else {
                    let mut v = Vec::new();
                    for a in args {
                        v.push(self.eval_expr(a.as_str(), line)?.as_number() as u64);
                    }
                    v
                };
                let mut results = Vec::new();
                for &id in &ids {
                    match self.host.llm_poll(id).map_err(|e| VmError::new("MLLM", e, line))? {
                        Some(result) => results.push(result),
                        None => {
                            self.state.yield_requested = true;
                            return Ok(Value::Null);
                        }
                    }
                }
                Ok(Value::String(results.join("|")))
            }
            func_name if func_name.starts_with("$$") => {
                // $$FUNC^ROUTINE(args) — user-defined function call
                self.return_value = None;
                let inner = func_name.strip_prefix("$$").unwrap_or_default();
                let (label, routine_name) = inner.split_once('^').unwrap_or((inner, ""));
                let source: String = if routine_name.is_empty() {
                    self.program.source.clone()
                } else {
                    self.host.routine(routine_name)
                    .map_err(|e| VmError::new("MROUTINE", e, line))?
                    .ok_or_else(|| VmError::new("MROUTINE",
                        format!("unknown routine {routine_name}"), line))?
                };
                let program = Compiler::compile(&source)
                    .map_err(|e| VmError::new("MCOMPILE", e, line))?;
                let label_upper = label.to_ascii_uppercase();
                let start_ip = *program.labels.get(&label_upper)
                    .ok_or_else(|| VmError::new("MLABEL",
                        format!("unknown label {label} in {routine_name}"), line))?;
                // Parse formal parameter names from source
                let formals = parse_formal_params(&source, &label_upper).unwrap_or_default();
                // Process raw args: evaluate values AND handle .ref references
                let mut evaluated: Vec<Value> = Vec::new();
                let mut refs: Vec<(String, String)> = Vec::new(); // (source_var, param_name)
                for (i, raw) in args.iter().enumerate() {
                    let trimmed = raw.trim();
                    let param_name = formals.get(i).cloned().unwrap_or_default();
                    if trimmed.starts_with('.') && !param_name.is_empty() {
                        let src_var = trimmed.trim_start_matches('.').trim().to_string();
                        if is_identifier(&src_var) {
                            // Copy array entries src_var → param_name
                            let prefix = format!("{}[", src_var);
                            let collected: Vec<(String, Value)> = self.state.vars.iter()
                                .filter(|(k, _)| k.starts_with(&prefix))
                                .map(|(k, v)| (k.clone(), v.clone()))
                                .collect();
                            for (key, val) in &collected {
                                let suffix = key.trim_start_matches(&prefix);
                                self.state.vars.insert(format!("{}[{}", param_name, suffix), val.clone());
                            }
                            refs.push((src_var, param_name));
                            evaluated.push(Value::Null); // placeholder
                            continue;
                        }
                    }
                    evaluated.push(self.eval_expr(raw, line)?);
                }
                let scope_base = self.state.local_scopes.len();
                self.bind_arguments(evaluated.clone());
                // Bind formal param names to positional args for non-refs
                for (i, pname) in formals.iter().enumerate() {
                    let trimmed = args.get(i).map(|a| a.trim()).unwrap_or("");
                    if !trimmed.starts_with('.') {
                        if let Some(val) = evaluated.get(i) {
                            self.state.vars.insert(pname.clone(), val.clone());
                        }
                    }
                }
                self.inline_depth += 1;
                let mut result = Err(VmError::new("MFUNCTION",
                    format!("{label} in {routine_name} did not QUIT"), line));
                let mut i = start_ip;
                while i < program.instructions.len() {
                    self.charge(line)?;
                    let ctrl = self.execute_instruction(&program.instructions[i])?;
                    match ctrl {
                        Control::Continue => i += 1,
                        Control::Skip(n) => i += 1 + n as usize,
                        Control::Quit => {
                            let rv = self.return_value.take().unwrap_or(Value::Null);
                            result = Ok(rv);
                            break;
                        }
                        Control::Halt | Control::Yield => break,
                    }
                }
                self.inline_depth -= 1;
                self.restore_local_scopes_to(scope_base);
                // Copy back any .ref array entries (param_name → source_var)
                for (src_var, param_name) in &refs {
                    let prefix = format!("{}[", param_name);
                    let collected: Vec<(String, Value)> = self.state.vars.iter()
                        .filter(|(k, _)| k.starts_with(&prefix))
                        .map(|(k, v)| (k.clone(), v.clone()))
                        .collect();
                    for (key, val) in &collected {
                        let suffix = key.trim_start_matches(&prefix);
                        self.state.vars.insert(format!("{}[{}", src_var, suffix), val.clone());
                    }
                }
                self.restore_arguments();
                result
            }
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
                    || flatten_local_sub(argument.trim()).as_ref().map_or(false, |k| self.state.vars.contains_key(k))
                    || argument.trim().starts_with('$')
                    || argument.trim().starts_with('@')
                    || argument.trim().starts_with('+')
                    || argument.trim().starts_with('-')
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

/// Extract formal parameter names from a routine source for a given label.
/// e.g., source="MYFUNC(x,y) Q x+y", label="MYFUNC" → Some(["x","y"])
fn parse_formal_params(source: &str, label: &str) -> Option<Vec<String>> {
    let label_upper = label.to_ascii_uppercase();
    for line in source.lines() {
        let trimmed = line.trim();
        let first_end = trimmed.find(|c: char| c.is_whitespace() || c == '(')
            .unwrap_or(trimmed.len());
        let token = &trimmed[..first_end];
        if token.to_ascii_uppercase() == label_upper {
            // Found the label definition, extract params from (a,b,c)
            if let Some(paren_open) = trimmed[first_end..].find('(') {
                let after_label = &trimmed[first_end + paren_open + 1..];
                if let Some(paren_close) = after_label.find(')') {
                    let params_str = &after_label[..paren_close];
                    let params: Vec<String> = params_str.split(',')
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty())
                        .collect();
                    if !params.is_empty() {
                        return Some(params);
                    }
                }
            }
            break;
        }
    }
    None
}

/// Flatten a local array reference like `m("type")` to `m["type"]`.
/// Returns None if the atom is not a local array subscript reference.
fn flatten_local_sub(atom: &str) -> Option<String> {
    let trimmed = atom.trim();
    // Must NOT start with ^ (global) or $ (special)
    if trimmed.starts_with('^') || trimmed.starts_with('$') {
        return None;
    }
    // Find first '(' before which we have an identifier
    let paren = trimmed.find('(')?;
    let name = trimmed[..paren].trim();
    if !is_identifier(name) {
        return None;
    }
    let rest = &trimmed[paren..];
    // Must end with matching ')'
    if !rest.ends_with(')') {
        return None;
    }
    let inner = rest[1..rest.len()-1].trim();
    // Evaluate subscripts: for now, take as literal string if quoted, or as number
    let sub_flat = if (inner.starts_with('"') && inner.ends_with('"') && inner.len() >= 2) {
        inner[1..inner.len()-1].to_string()
    } else if let Ok(n) = inner.parse::<f64>() {
        n.to_string()
    } else {
        inner.to_string()
    };
    Some(format!("{}[{}]", name, sub_flat))
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
                    | "I"
                    | "IF"
                    | "F"
                    | "FOR"
                    | "X"
                    | "XECUTE"
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

fn is_command_name(word: &str) -> bool {
    matches!(word.to_uppercase().as_str(),
        "B" | "BREAK" | "C" | "CLOSE" | "D" | "DO" | "E" | "ELSE" |
        "F" | "FOR" | "G" | "GOTO" | "H" | "HALT" | "HANG" |
        "I" | "IF" | "J" | "JOB" | "K" | "KILL" | "L" | "LOCK" |
        "M" | "MERGE" | "N" | "NEW" | "O" | "OPEN" |
        "Q" | "QUIT" | "R" | "READ" | "S" | "SET" |
        "TSTART" | "TCOMMIT" | "TC" | "TROLLBACK" | "TR" |
        "U" | "USE" | "V" | "VIEW" | "W" | "WRITE" |
        "X" | "XECUTE" | "ZWRITE" | "ZW" | "ZPRINT" | "ZP" | "ZBREAK" | "ZB"
    )
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
        // Strip trailing DO/D block marker (from FOR DO / IF DO patterns)
        // Only when followed by another command, not a routine call
        let trimmed = value.trim_end();
        let upper = trimmed.to_uppercase();
        if (upper.ends_with(" DO") || upper.ends_with(" D"))
            && trimmed.len() > 2
        {
            let before_do = &trimmed[..trimmed.len() - if upper.ends_with(" DO") { 3 } else { 2 }].trim_end();
            // Only strip if not followed by ^ (routine call)
            if !before_do.ends_with('^') {
                before_do
            } else {
                trimmed
            }
        } else {
            trimmed
        }
    }
}

fn split_for_body(value: &str) -> (&str, &str) {
    // Corte "tras el rango del spec": primer espacio top-level DESPUÉS del
    // primer '=' top-level con ≥1 carácter de rango ya leído.
    //   "i=1:1:3 S y=i"      → spec="i=1:1:3",   body="S y=i"
    //   "i = 1:1:3 S y=i"    → spec="i = 1:1:3", body="S y=i"
    fn cut_after_range(arg: &str) -> (&str, &str) {
        let mut depth = 0i32;
        let mut quoted = false;
        let mut seen_eq = false;
        let mut seen_range = false;
        for (index, ch) in arg.char_indices() {
            match ch {
                '"' => {
                    quoted = !quoted;
                    if seen_eq {
                        seen_range = true;
                    }
                }
                '(' if !quoted => depth += 1,
                ')' if !quoted => depth -= 1,
                '=' if !quoted && depth == 0 && !seen_eq => seen_eq = true,
                ch if ch.is_whitespace() && !quoted && depth == 0 && seen_eq && seen_range => {
                    return (arg[..index].trim(), arg[index..].trim());
                }
                ch if !ch.is_whitespace() && seen_eq => seen_range = true,
                _ => {}
            }
        }
        (arg, "")
    }

    let trimmed = value.trim();
    if let Some(space) = trimmed.find(char::is_whitespace) {
        let first_token = &trimmed[..space];
        if is_command_name(first_token) {
            // El argumento empieza con algo parecido a un comando. Puede ser:
            //  (a) un FOR infinito cuyo body arranca ya ("S k=$O(^T(k)) Q:k='' …"),
            //  (b) una variable de UNA LETRA que colisiona con un comando
            //      ("i = 1:1:3 …" → "I" es IF). Se distingue porque en (b) el '='
            //      pertenece al primer token (trimmed[..eq].trim() == first_token).
            if let Some(eq) = find_top_level(trimmed, "=") {
                if trimmed[..eq].trim() == first_token {
                    // (b): asignación del spec con espacios alrededor de '='
                    let rest = trimmed[eq + 1..].trim();
                    let body_start = rest
                        .find(char::is_whitespace)
                        .map(|sp| {
                            let (r, b) = (rest[..sp].trim(), rest[sp..].trim());
                            (format!("{first_token}={r}"), b.to_string())
                        });
                    // Reensamblamos spec="var=rango" y body; como devolvemos
                    // &str prestadas, construimos sobre `value` original:
                    // buscamos el espacio post-rango directamente.
                    let _ = body_start;
                    let mut depth = 0i32;
                    let mut quoted = false;
                    let mut seen_range = false;
                    for (index, ch) in trimmed.char_indices().skip(eq + 1) {
                        match ch {
                            '"' => {
                                quoted = !quoted;
                                seen_range = true;
                            }
                            '(' if !quoted => depth += 1,
                            ')' if !quoted => depth -= 1,
                            ch if ch.is_whitespace() && !quoted && depth == 0 && seen_range => {
                                return (trimmed[..index].trim(), trimmed[index..].trim());
                            }
                            ch if !ch.is_whitespace() => seen_range = true,
                            _ => {}
                        }
                    }
                    return (trimmed, "");
                }
            }
            return ("", trimmed);
        }
    }
    // Sin colisión con comando: el corte spec|body va en el primer espacio
    // top-level DESPUÉS del '=' con al menos un carácter de rango leído.
    //   "i=1:1:3 S y=i"   → spec="i=1:1:3", body="S y=i"
    let mut depth = 0i32;
    let mut quoted = false;
    let mut seen_eq = false;
    let mut seen_range_char = false;
    for (index, ch) in trimmed.char_indices() {
        match ch {
            '"' => {
                quoted = !quoted;
                if seen_eq {
                    seen_range_char = true;
                }
            }
            '(' if !quoted => depth += 1,
            ')' if !quoted => depth -= 1,
            '=' if !quoted && depth == 0 && !seen_eq => seen_eq = true,
            ch if ch.is_whitespace() && !quoted && depth == 0 && seen_eq && seen_range_char => {
                return (trimmed[..index].trim(), trimmed[index..].trim());
            }
            ch if !ch.is_whitespace() && seen_eq => seen_range_char = true,
            _ => {}
        }
    }
    (trimmed, "")
}

#[cfg(test)]
mod for_split_tests {
    #[test]
    fn split_for_body_cases() {
        let cases: Vec<(&str, &str, &str)> = vec![
            // (argumento del FOR, spec esperado, body esperado)
            ("i=1:1:3 S t=t+i W t", "i=1:1:3", "S t=t+i W t"),
            ("i = 1:1:3 S y=i",     "i = 1:1:3", "S y=i"),
            ("i=1:1:3 S t = t + i W \"x\"", "i=1:1:3", "S t = t + i W \"x\""),
            ("i=1,2,3 W i",         "i=1,2,3", "W i"),
            ("S k=$O(^T(k)) Q:k=\"\"", "", "S k=$O(^T(k)) Q:k=\"\""),
        ];
        for (input, want_spec, want_body) in cases {
            let (spec, body) = super::split_for_body(input);
            assert_eq!(spec, want_spec, "spec para {input:?}");
            assert_eq!(body, want_body, "body para {input:?}");
        }
    }
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
    // Must check '= BEFORE bare = to avoid matching the = of '=
    for &(pattern, op) in &[(">=", ">="), ("<=", "<="), ("'=", "'="), ("!=", "!="), ("[", "["), ("=", "="), (">", ">"), ("<", "<")] {
        if let Some(index) = find_top_level(value, pattern) {
            return Some((index, op));
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
            op @ (b'+' | b'-' | b'*' | b'/' | b'\\' | b'#' | b'_' | b'!' | b'&') if !quoted && depth == 0 => {
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
    // Logical operators: ! (OR), & (AND) — work on truthiness
    if operator == '!' {
        let l = left.truthy();
        let r = right.truthy();
        return Ok(Value::Bool(l || r));
    }
    if operator == '&' {
        let l = left.truthy();
        let r = right.truthy();
        return Ok(Value::Bool(l && r));
    }
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
        "!=" | "'=" => !ordering.is_eq(),
        ">" => ordering.is_gt(),
        "<" => ordering.is_lt(),
        ">=" => !ordering.is_lt(),
        "<=" => !ordering.is_gt(),
        "[" => left.as_string().contains(&right.as_string()),
        _ => false,
    }
}
