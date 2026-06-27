"""
MVM — M Virtual Machine + Device Manager

Cada "proceso" es un agente M que:
  - Vive en PDB (^PROCESSES y ^STATE)
  - Tiene su propio $J (PID), stack local, program counter
  - Se ejecuta en slices (cooperativo, no threads)
  - Tiene dispositivos I/O (0=chat, 1=dashboard, 51=log, 63=PDB, 99=mailbox)
"""

import time, json, re, os, random
from pathlib import Path


class MProcess:
    """Un proceso M vivo. Persiste en PDB entre slices."""

    def __init__(self, pid, code, pdb_module, name="", devices=None):
        self.pid = pid
        self.name = name
        self.code = code
        self.pc = 0
        self.pdb = pdb_module
        self.scope_vars = {}
        self.quit_flag = False
        self.created_at = time.time()
        self.last_run = time.time()
        self.status = "READY"
        self.devices = devices or DeviceManager(pdb_module)
        self._device_num = 0  # $IO
        self._load_state()

    def _load_state(self):
        try:
            r = self.pdb.tool_get({"ns": "STATE", "subs": [self.pid, "status"]})
            if r.get("found"):
                self.status = r.get("value", "READY")
            r = self.pdb.tool_get({"ns": "STATE", "subs": [self.pid, "vars"]})
            if r.get("found"):
                self.scope_vars = json.loads(r.get("value", "{}"))
        except:
            pass

    def _save_state(self):
        try:
            self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "status"], "value": self.status})
            self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "name"], "value": self.name})
            self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "vars"],
                              "value": json.dumps(self.scope_vars)})
            self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "last_run"],
                              "value": str(time.time())})
        except:
            pass

    def step(self, max_instructions=100):
        if self.status == "DEAD":
            return False
        if self.status == "HALTED":
            self._save_state()
            return True

        self.status = "RUNNING"
        self.last_run = time.time()

        lines = [l.strip() for l in self.code.split("\n") if l.strip()]
        inst_count = 0

        from m_light import MEvaluator
        m = MEvaluator(self.pdb)

        m.scope.vars = self.scope_vars.copy()
        m.scope.set('$J', str(self.pid))
        m.scope.set('$IO', str(self._device_num))

        while self.pc < len(lines) and inst_count < max_instructions:
            line = lines[self.pc]
            self.pc += 1
            if not line or line.startswith(";"):
                continue

            try:
                self._handle_device_ops(line)
                m._exec_line(line)
                inst_count += 1

                if m._quit_flag:
                    m._quit_flag = False
                    if self.pc >= len(lines):
                        self.status = "DEAD"
                        break
            except Exception as e:
                self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "error"],
                                  "value": f"PC={self.pc}: {e}"})
                self.pc += 1
                inst_count += 1

        self.scope_vars = {k: v for k, v in dict(m.scope.vars).items()
                          if not k.startswith('$')}

        if self.pc >= len(lines):
            self.status = "DEAD"

        self._save_state()
        return self.status != "DEAD"

    def _handle_device_ops(self, line):
        """Intercepta O/U/C/W para usar DeviceManager."""
        parts = line.strip().split()
        if not parts:
            return
        cmd = parts[0][0].upper()
        rest = " ".join(parts[1:])

        if cmd == 'O':
            num = re.match(r'(\d+)', rest)
            if num:
                self.devices.open(int(num.group(1)), rest[num.end():].strip())
        elif cmd == 'U':
            num = re.match(r'(\d+)', rest)
            if num:
                self._device_num = int(num.group(1))
        elif cmd == 'C':
            num = re.match(r'(\d+)', rest)
            if num:
                self.devices.close(int(num.group(1)))


class MVM:
    """M Virtual Machine — gestor de procesos M."""

    def __init__(self, pdb_module):
        self.pdb = pdb_module
        self.processes = {}
        self._next_pid = 1
        self.device_mgr = DeviceManager(pdb_module, self)
        self._load_processes()

    def _load_processes(self):
        try:
            pid = ""
            while True:
                r = self.pdb.tool_order({"ns": "PROCESSES", "subs": [pid], "direction": 1})
                if r.get("value") is None:
                    break
                pid = r["value"]
                code_r = self.pdb.tool_get({"ns": "PROCESSES", "subs": [pid, "code"]})
                name_r = self.pdb.tool_get({"ns": "PROCESSES", "subs": [pid, "name"]})
                if code_r.get("value"):
                    proc = MProcess(pid, code_r["value"], self.pdb,
                                   name=name_r.get("value", ""),
                                   devices=self.device_mgr)
                    self.processes[pid] = proc
                    if pid >= self._next_pid:
                        self._next_pid = pid + 1
        except:
            pass

    def spawn(self, code, name=""):
        pid = str(self._next_pid)
        self._next_pid += 1
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "code"], "value": code})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "name"], "value": name or f"proc_{pid}"})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "spawned_at"], "value": str(time.time())})

        proc = MProcess(pid, code, self.pdb, name=name, devices=self.device_mgr)
        self.device_mgr.attach_mailbox(pid, self)
        proc._save_state()
        self.processes[pid] = proc
        return pid

    def tick(self, max_per_process=100):
        alive = []
        for pid, proc in list(self.processes.items()):
            if proc.status == "DEAD":
                continue
            proc.step(max_per_process)
            if proc.status != "DEAD":
                alive.append(pid)
        return len(alive)

    def kill(self, pid):
        pid = str(pid)
        if pid in self.processes:
            self.processes[pid].status = "DEAD"
            self.processes[pid]._save_state()
            self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "status"], "value": "DEAD"})
            return True
        return False

    def list_processes(self):
        result = []
        for pid, proc in sorted(self.processes.items()):
            result.append({
                "pid": pid, "name": proc.name, "status": proc.status,
                "pc": proc.pc, "io_device": proc._device_num,
                "age": time.time() - proc.created_at,
                "last_run": time.time() - proc.last_run if proc.last_run else 0,
                "vars": len(proc.scope_vars),
            })
        return result

    def get_process(self, pid):
        return self.processes.get(str(pid))

    def mailbox_send(self, to_pid, message):
        to_pid = str(to_pid)
        next_id = f"msg_{int(time.time()*1000000)}_{random.randint(0,9999)}"
        self.pdb.tool_set({"ns": "STATE", "subs": [to_pid, "mailbox", next_id],
                          "value": str(message)})
        return next_id

    def mailbox_read(self, pid):
        pid = str(pid)
        msgs = []
        m_id = ""
        while True:
            r = self.pdb.tool_order({"ns": "STATE", "subs": [pid, "mailbox", m_id], "direction": 1})
            if r.get("value") is None:
                break
            m_id = r["value"]
            if m_id == "heartbeat":
                continue
            val = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
            msgs.append({"id": m_id, "content": val.get("value")})
            self.pdb.tool_kill({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
        return msgs


# ── Device Manager ──

class Device:
    def __init__(self, num, name):
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
    def __init__(self):
        super().__init__(0, "CHAT")
    def write(self, data):
        print(f"[DEV0] {data}")
    def read(self):
        return ""


class DashboardDevice(Device):
    def __init__(self, pdb=None):
        super().__init__(1, "DASHBOARD")
        self.pdb = pdb
    def write(self, data):
        if self.pdb:
            self.pdb.tool_set({"ns": "DASHBOARD", "subs": [str(time.time())], "value": data})


class LogDevice(Device):
    def __init__(self, pdb=None):
        super().__init__(51, "LOG")
        self.pdb = pdb
    def write(self, data):
        if self.pdb:
            self.pdb.tool_set({"ns": "LOG", "subs": [str(time.time())], "value": data})


class PDBDevice(Device):
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


class DeviceManager:
    def __init__(self, pdb_module=None, vm=None):
        self.devices = {}
        self._register_defaults(pdb_module, vm)

    def _register_defaults(self, pdb, vm):
        self.register(ConsoleDevice())
        self.register(DashboardDevice(pdb))
        self.register(LogDevice(pdb))
        self.register(PDBDevice(pdb))

    def register(self, device):
        self.devices[device.num] = device

    def open(self, num, params=""):
        d = self.devices.get(num)
        return d.open(params) if d else False

    def close(self, num):
        d = self.devices.get(num)
        if d: d.close(); return True
        return False

    def write(self, num, data):
        d = self.devices.get(num)
        if d and d.is_open: d.write(data); return True
        return False

    def read(self, num):
        d = self.devices.get(num)
        return d.read() if d and d.is_open else ""

    def list_devices(self):
        return [{"num": n, "name": d.name, "open": d.is_open}
                for n, d in sorted(self.devices.items())]

    def attach_mailbox(self, pid, vm):
        class _Mb(MailboxDevice):
            def __init__(self, vm, pid):
                super().__init__(99, "MAILBOX")
                self.vm, self.pid = vm, pid
            def write(self, data):
                if self.vm and self.pid:
                    self.vm.mailbox_send(self.pid, data)
            def read(self):
                if self.vm and self.pid:
                    msgs = self.vm.mailbox_read(self.pid)
                    return "\n".join(str(m.get("content","")) for m in msgs)
                return ""
        self.devices[99] = _Mb(vm, pid)
