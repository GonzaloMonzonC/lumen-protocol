"""
MVM — M Virtual Machine + Job System

Cada proceso (Job) es un agente M que:
  - Tiene su propio $J (job number, secuencial)
  - Tiene su propio $IO (dispositivo actual)
  - Vive en PDB (^PROCESSES y ^STATE)
  - Se ejecuta en slices cooperativos
  - Estados: READY → RUNNING → WAITING/BLOCKED → READY → ... → DEAD

Jobs:
  - Cada conexión (pdb_shell, terminal, etc.) = 1 Job
  - Jobs background tipo cron con timer
  - Comunicación via mailbox ($IO 99)
"""

import time, json, re, os, random, threading, urllib.request, urllib.error
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from io import BytesIO

# ── Estados de proceso ──
READY    = "READY"
RUNNING  = "RUNNING"
WAITING  = "WAITING"   # esperando mailbox/mensaje
BLOCKED  = "BLOCKED"   # esperando I/O (dispositivo ocupado)
HALTED   = "HALTED"    # pausado externamente
HIBERNATE= "HIBERNATE" # dormido, se despierta solo via ^SCHEDULE
DEAD     = "DEAD"

_ALL_STATES = [READY, RUNNING, WAITING, BLOCKED, HALTED, HIBERNATE, DEAD]


class MProcess:
    """Un proceso M vivo. Cada Job en el sistema."""

    def __init__(self, pid: int, code: str, pdb_module, name: str = "",
                 devices=None, owner: str = "", gas_limit: int = 1000, gas_budget: int = 0):
        self.pid = pid               # $J — entero secuencial
        self.name = name or f"job_{pid}"
        self.code = code
        self.pc = 0                  # program counter
        self.pdb = pdb_module
        self.scope_vars = {}         # variables locales M
        self.created_at = time.time()
        self.last_run = time.time()
        self.status = READY
        self.devices = devices or DeviceManager(pdb_module)
        self._device_num = 0         # $IO — dispositivo actual
        self.owner = owner           # identificador de conexión
        self.error = ""
        self.gas_limit = gas_limit   # max instrucciones por tick
        self.gas_budget = gas_budget    # 0 = ilimitado (legacy). >0 = total lifetime gas
        self.gas_used = 0            # instrucciones acumuladas (no resetea por tick)
        self.gas_total = 0           # total acumulado (vida del proceso, para max_gas_global)
        self._load_state()

    def _load_state(self):
        """Recuperar estado persistido en PDB."""
        try:
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "status"]})
            if r.get("found"):
                s = r.get("value", READY)
                self.status = s if s in _ALL_STATES else READY
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "vars"]})
            if r.get("found"):
                self.scope_vars = json.loads(r.get("value", "{}"))
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "pc"]})
            if r.get("found"):
                self.pc = int(r.get("value", 0))
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "io"]})
            if r.get("found"):
                self._device_num = int(r.get("value", 0))
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "gas_limit"]})
            if r.get("found"):
                self.gas_limit = int(r.get("value", 1000))
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "gas_budget"]})
            if r.get("found"):
                self.gas_budget = int(r.get("value", 0))
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(self.pid), "gas_total"]})
            if r.get("found"):
                self.gas_total = int(r.get("value", 0))
        except Exception:
            pass

    def _save_state(self):
        """Persistir estado actual a PDB."""
        try:
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "status"],
                              "value": self.status})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "name"],
                              "value": self.name})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "pc"],
                              "value": str(self.pc)})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "vars"],
                              "value": json.dumps(self.scope_vars)})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "last_run"],
                              "value": str(time.time())})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "io"],
                              "value": str(self._device_num)})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "gas_limit"],
                              "value": str(self.gas_limit)})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "gas_budget"],
                              "value": str(self.gas_budget)})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "gas_total"],
                              "value": str(self.gas_total)})
        except Exception:
            pass

    def step(self, max_instructions: int = 100) -> bool:
        """Ejecutar un slice del proceso. Retorna True si sigue vivo.
        gas_used: instrucciones en este tick (resetea cada llamada).
        gas_total: acumulado histórico. Yield si gas_used >= gas_limit.
        El scheduler llama repetidamente; cada llamada resetea gas_used."""
        if self.status == DEAD:
            return False
        if self.status in (WAITING, BLOCKED, HALTED, HIBERNATE):
            self._save_state()
            return True

        self.status = RUNNING
        self.last_run = time.time()
        # gas_used es acumulativo — no resetea por tick

        lines = [l.strip() for l in self.code.split("\n") if l.strip()]
        inst_count = 0

        from m_light import MEvaluator
        m = MEvaluator(self.pdb, device_manager=self.devices, current_io=self._device_num)
        m.scope.vars = self.scope_vars.copy()
        m.scope.set('$J', str(self.pid))
        m.scope.set('$IO', str(self._device_num))

        try:
            while self.pc < len(lines) and inst_count < max_instructions:
                line = lines[self.pc]
                self.pc += 1
                if not line or line.startswith(";"):
                    continue

                self._handle_device_ops(line)
                m._current_io = self._device_num  # sync $IO from MProcess
                m._exec_line(line)
                inst_count += 1
                self.gas_used += 1
                self.gas_total += 1

                # Yield si agotó el gas del tick
                if self.gas_used >= self.gas_limit:
                    self.status = READY
                    break

                # Preemption acumulativa: gas_budget > 0 y consumido
                if self.gas_budget > 0 and self.gas_used >= self.gas_budget:
                    self.status = DEAD
                    self.error = f"GAS_EXHAUSTED: consumido {self.gas_used}/{self.gas_budget} instrucciones"
                    self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "error"],
                                      "value": self.error})
                    break

                if m._quit_flag:
                    m._quit_flag = False
                    if self.pc >= len(lines):
                        self.pc = 0
                        break

        except Exception as e:
            self.error = f"PC={self.pc}: {e}"
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "error"],
                              "value": self.error})
            self.pc += 1

        # Preservar variables locales (no las $)
        self.scope_vars = {k: v for k, v in dict(m.scope.vars).items()
                          if not k.startswith('$')}

        # Si salimos del loop por max_instructions (no gas ni quit), marcar READY
        if self.status == RUNNING and self.pc < len(lines):
            self.status = READY

        if self.pc >= len(lines):
            self.pc = 0
            self.status = READY

        self._save_state()
        return self.status != DEAD

    def _handle_device_ops(self, line: str):
        """Intercepta O/U/C/W para usar DeviceManager."""
        parts = line.strip().split()
        if not parts:
            return
        cmd = parts[0][0].upper()
        rest = " ".join(parts[1:])

        if cmd == 'O':
            num = re.match(r'(\d+)', rest)
            if num:
                params = rest[num.end():].strip().lstrip(':').strip().strip('"').strip("'")
                params = params.replace('\\\\', '/').replace('\\', '/')  # normalize paths
                self.devices.open(int(num.group(1)), params)
        elif cmd == 'U':
            num = re.match(r'(\d+)', rest)
            if num:
                self._device_num = int(num.group(1))
        elif cmd == 'C':
            num = re.match(r'(\d+)', rest)
            if num:
                self.devices.close(int(num.group(1)))


class MVM:
    """M Virtual Machine — gestor de Jobs al estilo MSM.

    Cada Job es un MProcess con su $J único.
    El scheduler ejecuta round-robin sobre la ready queue.
    """

    def __init__(self, pdb_module, max_gas_global: int = 10000):
        self.pdb = pdb_module
        self.processes: dict[str, MProcess] = {}
        self._ready_queue: list[str] = []  # PIDs en orden RR
        self._next_pid = 1
        self._pid_lock = threading.Lock()
        self.device_mgr = DeviceManager(pdb_module, self)
        self.cron = CronScheduler(self)
        self._cron_counter = 0
        self.max_gas_global = max_gas_global  # límite global: si se excede → ABORT
        self._load_processes()

    def _load_processes(self):
        """Cargar procesos persistentes desde PDB."""
        try:
            pid = ""
            while True:
                r = self.pdb.tool_order({"ns": "PROCESSES", "subs": [pid], "direction": 1})
                if r.get("value") is None:
                    break
                pid = r["value"]
                code_r = self.pdb.tool_get({"ns": "PROCESSES", "subs": [pid, "code"]})
                name_r = self.pdb.tool_get({"ns": "PROCESSES", "subs": [pid, "name"]})
                owner_r = self.pdb.tool_get({"ns": "PROCESSES", "subs": [pid, "owner"]})
                if code_r.get("value"):
                    proc = MProcess(int(pid), code_r["value"], self.pdb,
                                   name=name_r.get("value", ""),
                                   devices=self.device_mgr,
                                   owner=owner_r.get("value", ""))
                    self.processes[pid] = proc
                    if proc.status == READY:
                        self._ready_queue.append(pid)
                    p = int(pid)
                    if p >= self._next_pid:
                        self._next_pid = p + 1
        except Exception:
            pass

    def new_pid(self) -> int:
        """Generar nuevo $J secuencial (thread-safe)."""
        with self._pid_lock:
            pid = self._next_pid
            self._next_pid += 1
            return pid

    def spawn(self, code: str, name: str = "", owner: str = "") -> int:
        """Crear un nuevo Job. Retorna su $J."""
        pid = self.new_pid()
        pid_str = str(pid)

        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid_str, "code"],
                          "value": code})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid_str, "name"],
                          "value": name or f"job_{pid}"})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid_str, "spawned_at"],
                          "value": str(time.time())})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid_str, "owner"],
                          "value": owner})

        proc = MProcess(pid, code, self.pdb, name=name,
                       devices=self.device_mgr, owner=owner)
        self.device_mgr.attach_mailbox(pid_str, self)
        proc._save_state()
        self.processes[pid_str] = proc
        self._ready_queue.append(pid_str)
        return pid

    def tick(self, max_per_process: int = 100) -> int:
        """Ejecutar un ciclo del scheduler round-robin.
        Retorna número de procesos vivos."""
        if not self._ready_queue:
            return len([p for p in self.processes.values()
                       if p.status not in (DEAD,)])

        # Round-robin: ejecutar el primero de la cola, rotar
        pid = self._ready_queue.pop(0)
        proc = self.processes.get(pid)

        if proc and proc.status == READY:
            proc.step(max_per_process)
            self._check_global_gas(proc)     # abortar si excede max_gas_global
            if proc.status == READY:
                self._ready_queue.append(pid)  # sigue en RR
            elif proc.status == DEAD:
                self._cleanup(pid)
            elif proc.status in (WAITING, BLOCKED, HALTED, HIBERNATE):
                pass  # no vuelve a RR hasta que cambie estado
        else:
            pass

        return len([p for p in self.processes.values()
                   if p.status not in (DEAD,)])

    def tick_all(self, max_per_process: int = 100) -> int:
        """Ejecutar TODOS los procesos READY (un ciclo completo RR).
        También revisa cron jobs cada 10 ticks y ^SCHEDULE cada tick."""
        # Check ^SCHEDULE: despertar procesos HIBERNATE cuyo wake_time haya llegado
        self._check_schedule()
        alive = 0
        seen = set()
        for _ in range(len(self._ready_queue)):
            if not self._ready_queue:
                break
            pid = self._ready_queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            proc = self.processes.get(pid)
            if proc and proc.status == READY:
                proc.step(max_per_process)
                self._check_global_gas(proc)   # abortar si excede max_gas_global
                if proc.status == READY:
                    self._ready_queue.append(pid)
                    alive += 1
                elif proc.status == DEAD:
                    self._cleanup(pid)
            elif proc and proc.status in (WAITING, BLOCKED, HALTED, HIBERNATE):
                pass
        self._cron_counter += 1
        if self._cron_counter % 10 == 0:
            self.cron.tick()
        if self._cron_counter % 5 == 0:
            self.llm_worker_tick()
        if self._cron_counter % 20 == 0:
            self.device_pool_tick()
        return alive

    def _check_schedule(self):
        """Revisar ^SCHEDULE y despertar procesos cuyo wake_time haya llegado."""
        now = time.time()
        pid = ""
        while True:
            r = self.pdb.tool_order({"ns": "SCHEDULE", "subs": [pid], "direction": 1})
            if r.get("value") is None:
                break
            pid = str(r["value"])
            val = self.pdb.tool_get({"ns": "SCHEDULE", "subs": [pid]})
            try:
                wake_time = float(val.get("value", 0))
            except (ValueError, TypeError):
                continue
            if wake_time <= now:
                # Wake this process
                self.wake_process(pid, from_schedule=True)
                self.pdb.tool_kill({"ns": "SCHEDULE", "subs": [pid]})

    def sleep_process(self, pid: int, seconds: float):
        """Dormir un proceso por N segundos (HIBERNATE)."""
        pid_str = str(pid)
        proc = self.processes.get(pid_str)
        if not proc:
            return False
        wake_time = time.time() + seconds
        self.pdb.tool_set({"ns": "SCHEDULE", "subs": [pid_str], "value": str(wake_time)})
        proc.status = HIBERNATE
        proc._save_state()
        return True

    def wake_process(self, pid, from_schedule=False):
        """Despertar un proceso HIBERNATE manualmente."""
        pid_str = str(pid) if not isinstance(pid, str) else pid
        proc = self.processes.get(pid_str)
        if not proc:
            return False
        if proc.status != HIBERNATE and not from_schedule:
            return False
        proc.status = READY
        proc.last_run = time.time()
        if pid_str not in self._ready_queue:
            self._ready_queue.append(pid_str)
        proc._save_state()
        # Clean up schedule entry
        self.pdb.tool_kill({"ns": "SCHEDULE", "subs": [pid_str]})
        return True

    def llm_worker_tick(self, max_per_tick: int = 3):  # updated: context field
        """Worker: poll ^LLM_PENDING, call LLM API, write ^LLM_RESULT, wake process."""
        import json, urllib.request, urllib.error, os, time
        processed = 0
        pid = ""
        while processed < max_per_tick:
            r = self.pdb.tool_order({"ns": "STATE", "subs": [pid], "direction": 1})
            if r.get("value") is None:
                break
            pid = str(r["value"])
            if pid in ("heartbeat",):
                continue

            # Get first pending seq for this pid
            seq = ""
            r2 = self.pdb.tool_order({"ns": "STATE", "subs": [pid, "llm_pending", ""], "direction": 1})
            if r2.get("value") is None:
                pid += "\xff"
                continue
            seq = str(r2["value"])
            if seq in ("heartbeat",):
                continue

            # Read the pending request
            data_r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "llm_pending", seq]})
            if data_r.get("value") is None:
                pid += "\xff"
                continue

            try:
                pending = json.loads(str(data_r["value"]))
            except Exception:
                self.pdb.tool_kill({"ns": "STATE", "subs": [pid, "llm_pending", seq]})
                pid += "\xff"
                continue

            context = pending.get("context", pending.get("prompt", ""))
            config = pending.get("config", {})

            # Call LLM API (OpenAI-compatible)
            api_key = os.environ.get("OPENAI_API_KEY", "")
            endpoint = os.environ.get("LLM_ENDPOINT", "https://api.openai.com/v1/chat/completions")

            response_text = ""
            if not api_key:
                response_text = "LLM_ERROR: No API key configured (set OPENAI_API_KEY)"
            else:
                body = json.dumps({
                    "model": config.get("model", "gpt-4"),
                    "messages": [{"role": "user", "content": context}],
                    "temperature": config.get("temperature", 0.7),
                    "max_tokens": config.get("max_tokens", 1024)
                }).encode()

                try:
                    req = urllib.request.Request(endpoint, data=body,
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {api_key}"
                        },
                        method="POST")
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        resp_data = json.loads(resp.read())
                        response_text = resp_data.get("choices", [{}])[0].get("message", {}).get("content", "")
                except Exception as e:
                    response_text = f"LLM_ERROR: {e}"

            # Write result to PDB
            self.pdb.tool_set({
                "ns": "STATE",
                "subs": [pid, "llm_result", seq],
                "value": json.dumps({"response": response_text, "completed": time.time()})
            })

            # Wake the waiting process
            self.wake(pid)

            processed += 1


    def device_pool_tick(self, max_idle: float = 120):
        """Clean up idle Device 77 sessions. Workers idle > max_idle get closed.
        Device 77 is shared via device_mgr, no per-process iteration needed."""
        dev = self.device_mgr.devices.get(77)
        if dev and dev.is_open and dev.idle_secs >= max_idle:
            # Log which processes had it open (for debugging)
            open_for = [str(p) for p, proc in self.processes.items()
                       if proc.devices.devices.get(77) is dev and dev.is_open]
            dev.close()
            if open_for:
                self.pdb.tool_set({
                    "ns": "STATE", "subs": [open_for[0], "llm_device_cleanup"],
                    "value": json.dumps({"idle_secs": dev.idle_secs, "cleaned": time.time()})
})
    def wake(self, pid):
        """Despertar un proceso en WAITING (ej: le llegó un mailbox)."""
        pid = str(pid)
        proc = self.processes.get(pid)
        if proc and proc.status == WAITING:
            proc.status = READY
            if pid not in self._ready_queue:
                self._ready_queue.append(pid)
            proc._save_state()
            return True
        return False

    def kill(self, pid) -> bool:
        """Terminar un Job."""
        pid = str(pid)
        proc = self.processes.get(pid)
        if proc:
            proc.status = DEAD
            proc._save_state()
            self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "status"],
                              "value": "DEAD"})
            self._cleanup(pid)
            return True
        return False

    def _cleanup(self, pid):
        """Limpiar un proceso muerto de las colas y ^SCHEDULE."""
        if pid in self._ready_queue:
            self._ready_queue.remove(pid)
        # Clean up any pending schedule entry
        self.pdb.tool_kill({"ns": "SCHEDULE", "subs": [str(pid)]})

    def _check_global_gas(self, proc: MProcess):
        """Abortar proceso si excede el límite global de gas total.
        Se ejecuta tras step(); si step() ya marcó DEAD, igual aplica."""
        if proc.gas_total >= self.max_gas_global:
            proc.status = DEAD
            proc.error = f"ABORTED: gas_total={proc.gas_total} >= max_gas_global={self.max_gas_global}"
            proc._save_state()
            self._cleanup(str(proc.pid))
            self.pdb.tool_set({"ns": "STATE", "subs": [str(proc.pid), "status"],
                              "value": "DEAD"})
            self.pdb.tool_set({"ns": "STATE", "subs": [str(proc.pid), "error"],
                              "value": proc.error})

    def list_processes(self) -> list[dict]:
        """Listar todos los Jobs con su estado."""
        result = []
        for pid, proc in sorted(self.processes.items(), key=lambda x: int(x[0])):
            result.append({
                "pid": int(pid),
                "name": proc.name,
                "status": proc.status,
                "pc": proc.pc,
                "io_device": proc._device_num,
                "age_secs": round(time.time() - proc.created_at, 1),
                "last_run_secs": round(time.time() - proc.last_run, 1) if proc.last_run else 0,
                "vars": len(proc.scope_vars),
                "owner": proc.owner,
                "error": proc.error,
                "gas_limit": proc.gas_limit,
                "gas_total": proc.gas_total,
            })
        return result

    def get_process(self, pid) -> MProcess | None:
        """Obtener un proceso por su $J."""
        return self.processes.get(str(pid))

    def get_process_by_owner(self, owner: str) -> MProcess | None:
        """Buscar proceso por identificador de conexión."""
        for proc in self.processes.values():
            if proc.owner == owner and proc.status != DEAD:
                return proc
        return None

    # ── Agent Outbox ────────────────────────────────────────────────────
    def outbox_send(self, pid, payload: str, priority: str = "normal",
                    msg_type: str = "text") -> int:
        """Send a structured message to the agent's outbox from a MVM process.
        No sub-subkeys — JSON entry includes status field.
        Returns message ID. Thread-safe via COUNTER."""
        pid_str = str(pid)
        msg_id = self.pdb.tool_incr({
            "ns": "AGENT_OUTBOX_COUNTER", "subs": [0]
        })
        entry = {
            "msg_id": int(msg_id.get("new_value", msg_id.get("value", 1))),
            "pid": int(pid) if pid_str.isdigit() else pid_str,
            "timestamp": time.time(),
            "type": msg_type,
            "payload": payload,
            "priority": priority,
            "status": "pending"
        }
        mid = str(entry["msg_id"])
        self.pdb.tool_set({
            "ns": "AGENT_OUTBOX", "subs": [mid],
            "value": json.dumps(entry)
        })
        return entry["msg_id"]

    def outbox_read(self, limit: int = 10, priority: str = "") -> list[dict]:
        """Read pending outbox messages. Ordered by priority DESC, time ASC.
        No sub-subkeys — $ORDER walks level-1 keys only."""
        messages = []
        mid = ""
        while True:
            r = self.pdb.tool_order({"ns": "AGENT_OUTBOX", "subs": [mid], "direction": 1})
            if r.get("value") is None:
                break
            mid = str(r["value"])
            # Skip counter entry
            if mid == "COUNTER" or not mid.isdigit():
                continue
            val = self.pdb.tool_get({"ns": "AGENT_OUTBOX", "subs": [mid]})
            if not val.get("value"):
                continue
            try:
                entry = json.loads(val["value"])
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
            if entry.get("status") == "pending":
                if priority and entry.get("priority") != priority:
                    continue
                messages.append(entry)
                if len(messages) >= limit:
                    break
        priority_order = {"high": 0, "normal": 1, "low": 2}
        messages.sort(key=lambda m: (
            priority_order.get(m.get("priority", "normal"), 9),
            m.get("timestamp", 0)
        ))
        return messages

    def outbox_ack(self, msg_id) -> bool:
        """Mark an outbox message as acknowledged (update JSON in-place)."""
        msg_id_str = str(msg_id)
        val = self.pdb.tool_get({"ns": "AGENT_OUTBOX", "subs": [msg_id_str]})
        if not val.get("value"):
            return False
        try:
            entry = json.loads(val["value"])
        except (json.JSONDecodeError, TypeError):
            return False
        entry["status"] = "acknowledged"
        entry["acknowledged_at"] = time.time()
        self.pdb.tool_set({
            "ns": "AGENT_OUTBOX", "subs": [msg_id_str],
            "value": json.dumps(entry)
        })
        return True

    def outbox_cleanup(self, max_age_secs: float = 86400):
        """Remove acknowledged messages older than max_age_secs."""
        now = time.time()
        mid = ""
        while True:
            r = self.pdb.tool_order({"ns": "AGENT_OUTBOX", "subs": [mid], "direction": 1})
            if r.get("value") is None:
                break
            mid = str(r["value"])
            if mid == "COUNTER" or not mid.isdigit():
                continue
            val = self.pdb.tool_get({"ns": "AGENT_OUTBOX", "subs": [mid]})
            if not val.get("value"):
                continue
            try:
                entry = json.loads(val["value"])
                if entry.get("status") == "acknowledged" and \
                   (now - entry.get("timestamp", 0)) > max_age_secs:
                    self.pdb.tool_kill({"ns": "AGENT_OUTBOX", "subs": [mid]})
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

    # ── Fork Cognitivo ──────────────────────────────────────────────────
    def fork(self, pid: int, name: str = "") -> int:
        """Clonar un proceso como un nuevo PID.
        Usa export_state() + import_state() para copia completa.
        Retorna el nuevo PID, o -1 si falla."""
        data = self.export_state(pid)
        if not data:
            return -1
        new_pid = self.import_state(data)
        if new_pid > 0 and name:
            proc = self.processes.get(new_pid)
            if proc:
                proc.name = name
                proc._save_state()
        return new_pid

    def diff_processes(self, pid_a: int, pid_b: int) -> dict:
        """Comparar estado entre dos procesos forkeados.
        Retorna diferencias en: scope_vars, pc, gas, status."""
        a = self.get_process(pid_a)
        b = self.get_process(pid_b)
        if not a or not b:
            return {"error": f"Proceso(s) no encontrado: pid_a={pid_a}, pid_b={pid_b}"}
        
        diff = {
            "pid_a": pid_a,
            "pid_b": pid_b,
            "pc": {"a": a.pc, "b": b.pc, "diff": a.pc != b.pc},
            "status": {"a": a.status, "b": b.status, "diff": a.status != b.status},
            "gas_used": {"a": a.gas_used, "b": b.gas_used, "diff": a.gas_used != b.gas_used},
            "gas_total": {"a": a.gas_total, "b": b.gas_total, "diff": a.gas_total != b.gas_total},
            "vars_diff": {},
            "vars_only_in_a": [],
            "vars_only_in_b": [],
        }
        
        # Comparar scope_vars
        all_keys = set(a.scope_vars.keys()) | set(b.scope_vars.keys())
        for k in sorted(all_keys):
            va = a.scope_vars.get(k)
            vb = b.scope_vars.get(k)
            if va != vb:
                if k in a.scope_vars and k in b.scope_vars:
                    diff["vars_diff"][k] = {"a": va, "b": vb}
                elif k in a.scope_vars:
                    diff["vars_only_in_a"].append(k)
                else:
                    diff["vars_only_in_b"].append(k)
        
        return diff

    def promote(self, source_pid: int, target_pid: int = None) -> dict:
        """Copiar estado de source_pid a target_pid y matar source.
        Si target_pid no se especifica, se usa el PID original (el primero de la cadena).
        Retorna {status, target_pid}."""
        src = self.get_process(source_pid)
        if not src:
            return {"status": "error", "error": f"Source PID {source_pid} no encontrado"}
        
        # Export source state
        data = self.export_state(source_pid)
        if not data:
            return {"status": "error", "error": f"No se pudo exportar pid={source_pid}"}
        
        if target_pid is None:
            # Si no hay target, crear nuevo PID y matar source
            new_pid = self.import_state(data)
            self.kill(source_pid)
            return {"status": "promoted", "source_pid": source_pid, "target_pid": new_pid}
        
        # Import sobre target existente: kill target, re-import
        target = self.get_process(target_pid)
        if not target:
            return {"status": "error", "error": f"Target PID {target_pid} no encontrado"}
        
        # Kill old target state
        self.pdb.tool_kill({"ns": "STATE", "subs": [str(target_pid)]})
        self.pdb.tool_kill({"ns": "PROCESSES", "subs": [str(target_pid)]})
        
        # Create fresh process with same PID
        code = data.get("code", "")
        name = data.get("name", f"promoted_{source_pid}_to_{target_pid}")
        
        proc = MProcess(target_pid, code, self.pdb, name=name, 
                        devices=self.device_mgr, owner=data.get("owner", ""))
        proc.pc = data.get("pc", 0)
        proc.status = data.get("status", "READY")
        proc.scope_vars = dict(data.get("scope_vars", {}))
        proc.gas_limit = data.get("gas_limit", 1000)
        proc.gas_budget = data.get("gas_budget", 0)
        proc.gas_used = data.get("gas_used", 0)
        proc.gas_total = data.get("gas_total", 0)
        proc._device_num = data.get("device_num", 0)
        proc.owner = data.get("owner", "")
        
        self.processes[str(target_pid)] = proc
        self.device_mgr.attach_mailbox(str(target_pid), self)
        
        if proc.status == READY and str(target_pid) not in self._ready_queue:
            self._ready_queue.append(str(target_pid))
        
        proc._save_state()
        
        # Kill source
        self.kill(source_pid)
        
        return {"status": "promoted", "source_pid": source_pid, "target_pid": target_pid}
    def mailbox_send(self, to_pid, message: str) -> str:
        """Enviar mensaje a mailbox de otro Job."""
        to_pid = str(to_pid)
        msg_id = f"m{int(time.time()*1000000)}_{random.randint(0,9999)}"
        self.pdb.tool_set({"ns": "STATE", "subs": [to_pid, "mailbox", msg_id],
                          "value": str(message)})
        # Despertar al proceso destino si está WAITING
        self.wake(to_pid)
        return msg_id

    def mailbox_read(self, pid) -> list[dict]:
        """Leer mensajes del mailbox de un Job."""
        pid = str(pid)
        msgs = []
        m_id = ""
        while True:
            r = self.pdb.tool_order({"ns": "STATE", "subs": [pid, "mailbox", m_id],
                                    "direction": 1})
            if r.get("value") is None:
                break
            m_id = r["value"]
            if m_id in ("heartbeat",):
                continue
            val = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
            msgs.append({"id": m_id, "content": val.get("value")})
            self.pdb.tool_kill({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
        return msgs



    def export_state(self, pid) -> dict:
        """Export complete process state as JSON-serializable dict.
        Includes: scope_vars, pc, status, mailbox, metadata.
        Suitable for cross-node transfer and resurrection.
        Returns empty dict if process not found."""
        pid = str(pid)
        proc = self.processes.get(int(pid)) if isinstance(pid, str) and pid.isdigit() else None
        if not proc and pid not in self.processes:
            # Try to load from PDB STATE namespace
            pass  # will try PDB directly
        
        result = {}
        
        # Core process fields
        if proc:
            result["pid"] = proc.pid
            result["name"] = proc.name
            result["code"] = proc.code
            result["pc"] = proc.pc
            result["status"] = proc.status
            result["scope_vars"] = dict(proc.scope_vars)
            result["gas_limit"] = proc.gas_limit
            result["gas_budget"] = proc.gas_budget
            result["gas_used"] = proc.gas_used
            result["gas_total"] = proc.gas_total
            result["owner"] = proc.owner
            result["error"] = proc.error
            result["device_num"] = proc._device_num
            result["created_at"] = proc.created_at
            result["last_run"] = proc.last_run
        else:
            # Load from PDB STATE directly
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "name"]})
            if not r.get("found", True) and r.get("value") is None:
                return {}  # process not found
            result["pid"] = int(pid)
            result["name"] = r.get("value", "")
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "status"]})
            result["status"] = r.get("value", "DEAD")
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "pc"]})
            result["pc"] = int(r.get("value", 0)) if r.get("value") else 0
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "vars"]})
            result["scope_vars"] = json.loads(r.get("value", "{}")) if r.get("value") else {}
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "gas_limit"]})
            result["gas_limit"] = int(r.get("value", 1000))
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "gas_total"]})
            result["gas_total"] = int(r.get("value", 0))
            result["gas_used"] = 0
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "owner"]})
            result["owner"] = r.get("value", "")
            r = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "io"]})
            result["device_num"] = int(r.get("value", 0))
            result["code"] = ""
            result["error"] = ""
            result["created_at"] = 0.0
            result["last_run"] = 0.0
        
        # Collect mailbox messages
        mailbox_msgs = []
        m_id = ""
        while True:
            r = self.pdb.tool_order({"ns": "STATE", "subs": [pid, "mailbox", m_id], "direction": 1})
            if r.get("value") is None:
                break
            m_id = r["value"]
            if m_id in ("heartbeat",):
                continue
            val = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
            mailbox_msgs.append({"id": m_id, "content": val.get("value")})
        result["mailbox"] = mailbox_msgs
        
        result["_export_version"] = 1
        result["_exported_at"] = time.time()
        return result

    def import_state(self, data: dict) -> int:
        """Import a process from exported state dict.
        Creates a NEW process with a fresh PID.
        Returns the new PID, or -1 on failure."""
        import copy
        data = copy.deepcopy(data)
        
        # Validate
        # Allocate new PID (even with empty code, export should work)
        new_pid = self._next_pid
        self._next_pid += 1
        
        code = data.get("code", "")
        name = data.get("name", f"restored_{new_pid}")
        owner = data.get("owner", "")
        
        # Create process
        proc = MProcess(new_pid, code, self.pdb, name=name, owner=owner,
                        gas_limit=data.get("gas_limit", 1000),
                        gas_budget=data.get("gas_budget", 0))
        
        # Restore state
        proc.pc = data.get("pc", 0)
        proc.status = data.get("status", "READY")
        proc.scope_vars = dict(data.get("scope_vars", {}))
        proc.gas_total = data.get("gas_total", 0)
        proc.gas_used = data.get("gas_used", 0)
        proc.gas_budget = data.get("gas_budget", 0)
        proc._device_num = data.get("device_num", 0)
        proc.error = data.get("error", "")
        proc.created_at = data.get("created_at", time.time())
        proc.last_run = data.get("last_run", time.time())
        
        # Restore mailbox
        for msg in data.get("mailbox", []):
            msg_id = msg.get("id", f"m{int(time.time()*1000000)}_{random.randint(0,9999)}")
            content = msg.get("content", "")
            self.pdb.tool_set({"ns": "STATE", "subs": [str(new_pid), "mailbox", msg_id],
                              "value": str(content)})
        
        # Register and persist
        self.processes[str(new_pid)] = proc
        proc._save_state()
        
        return new_pid

    def state_save(self, pid) -> bool:
        """Export process state and save as single blob under ^STATE(pid, 'snapshot')."""
        data = self.export_state(pid)
        if not data:
            return False
        try:
            self.pdb.tool_set({"ns": "STATE", "subs": [str(pid), "snapshot"],
                              "value": json.dumps(data)})
            return True
        except Exception:
            return False

    def state_restore(self, pid) -> int:
        """Restore a process from a previously saved snapshot.
        Returns new PID, or -1 on failure."""
        try:
            r = self.pdb.tool_get({"ns": "STATE", "subs": [str(pid), "snapshot"]})
            if not r.get("value"):
                return -1
            data = json.loads(r.get("value", "{}"))
            return self.import_state(data)
        except Exception:
            return -1

# ══════════════════════════════════════════════════════════════════
# Device Manager
# ══════════════════════════════════════════════════════════════════

class Device:
    def __init__(self, num: int, name: str):
        self.num = num
        self.name = name
        self.is_open = False

    def open(self, params=""):
        self.is_open = True
        return True

    def read(self):
        return ""

    def write(self, data):
        pass

    def close(self):
        self.is_open = False


class ConsoleDevice(Device):
    """Device 0 — terminal/consola del Job."""
    def __init__(self, write_cb=None):
        super().__init__(0, "CONSOLE")
        self.write_cb = write_cb
        self.buffer = []

    def write(self, data):
        self.buffer.append(str(data))
        if self.write_cb:
            self.write_cb(data)
        else:
            print(f"[JOB:{self._pid}] {data}")

    def read(self):
        return self.buffer.pop(0) if self.buffer else ""

    def flush(self):
        out = "\n".join(self.buffer)
        self.buffer = []
        return out


class HTTPDevice(Device):
    """Device 8 — Cliente HTTP moderno (webhooks, APIs).
    OPEN con: "GET https://..." o "POST https://..."
    WRITE: body del request
    READ: respuesta (status + body)
    """
    def __init__(self):
        super().__init__(8, "HTTP")
        self._url = ""
        self._method = "GET"
        self._headers = {"Content-Type": "application/json"}
        self._last_response = ""
        self._last_status = 0

    def open(self, params=""):
        """OPEN 8:"POST https://api.example.com/hook" o "GET https://..." """
        parts = params.strip().split(None, 1)
        if len(parts) == 2:
            self._method = parts[0].upper()
            self._url = parts[1]
        elif parts:
            self._url = parts[0]
        self.is_open = True
        return True

    def write(self, data):
        if not self._url:
            return
        body = data.encode() if isinstance(data, str) else data
        try:
            req = urllib.request.Request(
                self._url, data=body, method=self._method,
                headers=self._headers
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                self._last_status = resp.status
                self._last_response = resp.read().decode('utf-8', errors='replace')
        except urllib.error.HTTPError as e:
            self._last_status = e.code
            self._last_response = e.read().decode('utf-8', errors='replace')
        except Exception as e:
            self._last_status = 0
            self._last_response = f"ERROR: {e}"

    def read(self):
        return json.dumps({"status": self._last_status, "body": self._last_response})


class WebhookDevice(Device):
    """Device 9 — Receptor de webhooks (HTTP server mínimo).
    OPEN con "host:puerto" ej ":9090" o "0.0.0.0:9090"
    READ: siguiente payload recibido (cola FIFO)
    CLOSE: detiene el servidor
    """
    class _Handler(BaseHTTPRequestHandler):
        queue = []
        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8', errors='replace') if length else ""
            self.__class__.queue.append({
                "path": self.path, "headers": dict(self.headers),
                "body": body, "method": "POST"
            })
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        do_GET = do_POST
        do_PUT = do_POST
        def log_message(self, *a): pass

    def __init__(self):
        super().__init__(9, "WEBHOOK")
        self._server = None
        self._thread = None

    def open(self, params=""):
        addr = params.strip() or ":0"
        host, _, port = addr.partition(":")
        port = int(port) if port else 0
        self.__class__._Handler.queue = []
        self._server = HTTPServer((host or "0.0.0.0", port), self.__class__._Handler)
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        self.is_open = True
        return True

    def read(self):
        q = self.__class__._Handler.queue
        if not q:
            return json.dumps({"queued": 0})
        item = q.pop(0)
        item["queued"] = len(q)
        return json.dumps(item)

    def close(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self.is_open = False


class DashboardDevice(Device):
    """Device 1 — dashboard PDB."""
    def __init__(self, pdb=None):
        super().__init__(1, "DASHBOARD")
        self.pdb = pdb

    def write(self, data):
        if self.pdb:
            self.pdb.tool_set({"ns": "DASHBOARD", "subs": [str(time.time())],
                              "value": str(data)})


class LogDevice(Device):
    """Device 51 — log a PDB."""
    def __init__(self, pdb=None):
        super().__init__(51, "LOG")
        self.pdb = pdb

    def write(self, data):
        if self.pdb:
            self.pdb.tool_set({"ns": "LOG", "subs": [str(time.time())],
                              "value": str(data)})


class PDBDevice(Device):
    """Device 63 — acceso directo a PDB."""
    def __init__(self, pdb=None):
        super().__init__(63, "PDB")
        self.pdb = pdb

    def write(self, data):
        m = re.match(r'\^(\w+)\((.+)\)=(.*)', data)
        if m and self.pdb:
            ns = m.group(1)
            subs = [s.strip().strip('"') for s in m.group(2).split(',')]
            val = m.group(3).strip().strip('"')
            self.pdb.tool_set({"ns": ns, "subs": subs, "value": val})

    def read(self):
        return "^PDB OK"


class MailboxDevice(Device):
    """Device 99 — IPC mailbox entre Jobs."""
    def __init__(self, vm=None, pid=None):
        super().__init__(99, "MAILBOX")
        self.vm = vm
        self._pid = pid

    def write(self, data):
        if self.vm and self._pid:
            self.vm.mailbox_send(self._pid, str(data))

    def read(self):
        if self.vm and self._pid:
            msgs = self.vm.mailbox_read(self._pid)
            return "\n".join(str(m.get("content", "")) for m in msgs)
        return ""



class LLMDevice(Device):
    """Device 77 -- LLM Engine Stream. Storage-based async inference.
    OPEN 77:"model=gpt-4&temp=0.7&max_tokens=2048"
    WRITE: accumulate prompt in persistent buffer (stays across reads)
    READ: submit accumulated context to ^LLM_PENDING, wait for ^LLM_RESULT,
          then APPEND response to buffer for next turn
    CLOSE: cleanup buffer and pending state
    POOL: workers use HIBERNATE while idle, cleaned up after timeout"""

    def __init__(self, vm=None, pid=None):
        super().__init__(77, "LLM")
        self.vm = vm
        self._pid = pid
        self.buffer = []
        self.config = {"model": "gpt-4", "temperature": 0.7, "max_tokens": 1024}
        self._seq = 0
        self._pending = False
        self._result = None
        self._last_activity = time.time()
        self._active_workers = set()  # pool of worker pids using this device

    def open(self, params=""):
        """OPEN 77:"model=gpt-4&temp=0.7&max_tokens=2048" """
        for pair in params.strip().split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k == "model":
                    self.config["model"] = v
                elif k in ("temp", "temperature"):
                    self.config["temperature"] = float(v)
                elif k in ("max", "max_tokens"):
                    self.config["max_tokens"] = int(v)
        self.buffer = []
        self._pending = False
        self._result = None
        self._last_activity = time.time()
        self.is_open = True
        return True

    def write(self, data):
        """WRITE: accumulate in persistent buffer (survives READ cycles).
        The buffer holds the full conversation context."""
        self.buffer.append(str(data))
        self._last_activity = time.time()

    def read(self):
        """READ: submit buffer to worker, wait for response, append to buffer.
        Buffer stays intact for the next WRITE cycle (conversational context)."""
        self._last_activity = time.time()

        # If we have a cached result from a previous check, return it
        if self._result is not None:
            r = self._result
            self._result = None
            self._pending = False
            return r

        # If no pending request and buffer has data, submit
        if not self._pending and self.buffer:
            full_context = "\n".join(self.buffer)
            self._seq += 1
            seq = self._seq

            if self.vm and self._pid:
                self.vm.pdb.tool_set({
                    "ns": "STATE",
                    "subs": [str(self._pid), "llm_pending", str(seq)],
                    "value": json.dumps({
                        "context": full_context,
                        "config": dict(self.config),
                        "created": time.time(),
                        "turn": seq
                    })
                })
                self._pending = True

                # Mark process as WAITING
                proc = self.vm.get_process(self._pid)
                if proc:
                    proc.status = "WAITING"
                    proc.wait_reason = "LLM_INFERENCE"
                    proc._save_state()

            return ""  # No result yet, retry next tick

        # Check for result from worker
        if self._pending and self.vm and self._pid:
            result = self.vm.pdb.tool_get({
                "ns": "STATE",
                "subs": [str(self._pid), "llm_result", str(self._seq)]
            })
            if result.get("value") is not None:
                try:
                    data = json.loads(result.get("value", "{}"))
                    response = data.get("response", "")

                    # APPEND response to buffer for conversational context
                    self.buffer.append(response)

                    # Cleanup pending entries
                    self.vm.pdb.tool_kill({
                        "ns": "STATE",
                        "subs": [str(self._pid), "llm_pending", str(self._seq)]
                    })
                    self.vm.pdb.tool_kill({
                        "ns": "STATE",
                        "subs": [str(self._pid), "llm_result", str(self._seq)]
                    })

                    self._result = response
                    self._pending = False
                    return ""  # Return cached result on next read() call
                except Exception:
                    pass

        return ""

    def close(self):
        """CLOSE: cleanup buffer, pending state, and worker pool."""
        self.buffer = []
        self._pending = False
        self._result = None
        if self._pid and self.vm:
            self.vm.pdb.tool_kill({
                "ns": "STATE",
                "subs": [str(self._pid), "llm_pending"]
            })
            self.vm.pdb.tool_kill({
                "ns": "STATE",
                "subs": [str(self._pid), "llm_result"]
            })
        self._active_workers.clear()
        self.is_open = False

    @property
    def idle_secs(self) -> float:
        """Seconds since last activity (WRITE/READ)."""
        return time.time() - self._last_activity


class FileDevice(Device):
    """Device 5 — File I/O. OPEN con filepath, WRITE/READ/CLOSE."""
    def __init__(self):
        super().__init__(5, "FILE")
        self._filepath = ""
        self._mode = "w"
        self._handle = None

    def open(self, params=""):
        """OPEN 5:"/path/to/file" o "w /path/to/file" o "r /path/to/file" """
        params = params.strip().strip('"').strip("'")
        parts = params.split(None, 1)
        if len(parts) == 2:
            self._mode = parts[0]
            self._filepath = parts[1]
        elif parts:
            self._filepath = parts[0]
        try:
            if self._handle:
                self._handle.close()
            self._handle = open(self._filepath, self._mode)
            self.is_open = True
            return True
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.is_open = False
            return False

    def write(self, data):
        if self._handle and self.is_open:
            self._handle.write(str(data))
            self._handle.flush()

    def read(self):
        if self._handle and self.is_open:
            if self._mode == "r":
                return self._handle.read()
            self._handle.seek(0)
            return self._handle.read()
        return ""

    def close(self):
        if self._handle:
            self._handle.close()
            self._handle = None
        self.is_open = False


class SocketDevice(Device):
    """Device 7 — TCP Socket client. OPEN "host:port", WRITE/READ, CLOSE."""
    def __init__(self):
        super().__init__(7, "SOCKET")
        self._host = ""
        self._port = 0
        self._sock = None
        self._buffer = ""

    def open(self, params=""):
        """OPEN 7:"localhost:8080" """
        parts = params.strip().split(":", 1)
        if len(parts) == 2:
            self._host = parts[0]
            try:
                self._port = int(parts[1])
            except ValueError:
                return False
            try:
                import socket
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(10)
                self._sock.connect((self._host, self._port))
                self.is_open = True
                return True
            except Exception:
                self._sock = None
                return False
        return False

    def write(self, data):
        if self._sock and self.is_open:
            try:
                self._sock.sendall(str(data).encode())
            except Exception:
                self.is_open = False

    def read(self):
        if self._sock and self.is_open:
            try:
                self._sock.settimeout(0.5)
                chunk = self._sock.recv(4096)
                return chunk.decode('utf-8', errors='replace') if chunk else ""
            except Exception:
                return ""
        return ""

    def close(self):
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self.is_open = False


class DeviceManager:
    """Gestor de dispositivos I/O. Cada proceso tiene acceso a todos."""

    def __init__(self, pdb_module=None, vm=None):
        self.devices: dict[int, Device] = {}
        self._vm = vm
        self._register_defaults(pdb_module, vm)

    def _register_defaults(self, pdb, vm):
        self.register(ConsoleDevice())
        self.register(FileDevice())
        self.register(SocketDevice())
        self.register(DashboardDevice(pdb))
        self.register(LogDevice(pdb))
        self.register(PDBDevice(pdb))
        self.register(HTTPDevice())
        self.register(WebhookDevice())
        self.register(LLMDevice())

    def register(self, device: Device):
        self.devices[device.num] = device

    def open(self, num: int, params=""):
        d = self.devices.get(num)
        return d.open(params) if d else False

    def close(self, num: int):
        d = self.devices.get(num)
        if d:
            d.close()
            return True
        return False

    def write(self, num: int, data) -> bool:
        d = self.devices.get(num)
        if d and d.is_open:
            d.write(data)
            return True
        return False

    def read(self, num: int) -> str:
        d = self.devices.get(num)
        return d.read() if d and d.is_open else ""

    def list_devices(self) -> list[dict]:
        return [{"num": n, "name": d.name, "open": d.is_open}
                for n, d in sorted(self.devices.items())]

    def attach_mailbox(self, pid: str, vm):
        self.devices[99] = MailboxDevice(vm, pid)
        if 77 in self.devices:
            dev = self.devices[77]
            dev.vm = vm
            dev._pid = pid


# ══════════════════════════════════════════════════════════════════
# Cron Scheduler — Jobs programados por timer
# ══════════════════════════════════════════════════════════════════

class CronScheduler:
    """Gestor de cron jobs. Cada entrada ejecuta M code o llama a un webhook
    en un intervalo fijo. Persistente en ^CRON."""

    def __init__(self, mvm: 'MVM'):
        self.mvm = mvm
        self.pdb = mvm.pdb

    def add(self, name: str, interval_secs: float, action: str,
            action_type: str = "mcode", enabled: bool = True):
        """Registrar un cron job.

        Args:
            name: identificador único
            interval_secs: cada cuantos segundos ejecutar
            action: código M a ejecutar (action_type="mcode") o URL (action_type="webhook")
            action_type: "mcode" | "webhook"
        """
        entry = {
            "name": name,
            "interval": interval_secs,
            "action": action,
            "type": action_type,
            "enabled": enabled,
            "last_run": 0.0,
            "created": time.time(),
        }
        self.pdb.tool_set({"ns": "CRON", "subs": [name], "value": json.dumps(entry)})
        return name

    def remove(self, name: str):
        """Eliminar un cron job."""
        self.pdb.tool_kill({"ns": "CRON", "subs": [name]})

    def list(self) -> list[dict]:
        """Listar todos los cron jobs."""
        jobs = []
        n = ""
        while True:
            r = self.pdb.tool_order({"ns": "CRON", "subs": [n], "direction": 1})
            if r.get("value") is None:
                break
            n = r["value"]
            val = self.pdb.tool_get({"ns": "CRON", "subs": [n]})
            try:
                entry = json.loads(val.get("value", "{}"))
                jobs.append(entry)
            except (json.JSONDecodeError, TypeError):
                pass
        return jobs

    def tick(self) -> int:
        """Revisar y disparar cron jobs cuyo intervalo haya vencido.
        Retorna número de jobs disparados en este tick."""
        fired = 0
        now = time.time()
        for entry in self.list():
            if not entry.get("enabled", True):
                continue
            interval = entry.get("interval", 60)
            last = entry.get("last_run", 0)
            if now - last >= interval:
                self._fire(entry)
                entry["last_run"] = now
                self.pdb.tool_set({"ns": "CRON", "subs": [entry["name"]],
                                   "value": json.dumps(entry)})
                fired += 1
        return fired

    def _fire(self, entry: dict):
        """Ejecutar la acción de un cron job."""
        name = entry.get("name", "cron")
        action = entry.get("action", "")
        atype = entry.get("type", "mcode")

        if atype == "webhook":
            # Disparar webhook: spawn un job que hace un HTTP POST
            code = (
                f'O 8:"POST {action}"\n'
                f'U 8\n'
                f'W ""\n'
            )
            self.mvm.spawn(code, name=f"cron:{name}")
        else:
            # Ejecutar código M directamente
            self.mvm.spawn(action, name=f"cron:{name}")


# Fase 6 is opt-in while the Python scheduler remains the safe fallback. The
# public MVM name stays stable for pdb_tools and every MCP bridge.
PythonMVM = MVM
if os.environ.get("MVM_ENGINE", "python").strip().lower() in ("rust", "tokio"):
    try:
        from lumen_mvm import TokioMVM, available as _tokio_mvm_available
        if _tokio_mvm_available():
            MVM = TokioMVM
    except (ImportError, OSError, RuntimeError):
        MVM = PythonMVM
