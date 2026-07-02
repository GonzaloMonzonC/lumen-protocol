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
DEAD     = "DEAD"

_ALL_STATES = [READY, RUNNING, WAITING, BLOCKED, HALTED, DEAD]


class MProcess:
    """Un proceso M vivo. Cada Job en el sistema."""

    def __init__(self, pid: int, code: str, pdb_module, name: str = "",
                 devices=None, owner: str = ""):
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
        except Exception:
            pass

    def step(self, max_instructions: int = 100) -> bool:
        """Ejecutar un slice del proceso. Retorna True si sigue vivo."""
        if self.status == DEAD:
            return False
        if self.status in (WAITING, BLOCKED, HALTED):
            self._save_state()
            return True

        self.status = RUNNING
        self.last_run = time.time()

        lines = [l.strip() for l in self.code.split("\n") if l.strip()]
        inst_count = 0

        from m_light import MEvaluator
        m = MEvaluator(self.pdb)
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
                m._exec_line(line)
                inst_count += 1

                if m._quit_flag:
                    m._quit_flag = False
                    if self.pc >= len(lines):
                        self.status = DEAD
                        break

        except Exception as e:
            self.error = f"PC={self.pc}: {e}"
            self.pdb.tool_set({"ns": "STATE", "subs": [str(self.pid), "error"],
                              "value": self.error})
            self.pc += 1

        # Preservar variables locales (no las $)
        self.scope_vars = {k: v for k, v in dict(m.scope.vars).items()
                          if not k.startswith('$')}

        if self.pc >= len(lines):
            self.status = DEAD

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
    """M Virtual Machine — gestor de Jobs al estilo MSM.

    Cada Job es un MProcess con su $J único.
    El scheduler ejecuta round-robin sobre la ready queue.
    """

    def __init__(self, pdb_module):
        self.pdb = pdb_module
        self.processes: dict[str, MProcess] = {}
        self._ready_queue: list[str] = []  # PIDs en orden RR
        self._next_pid = 1
        self._pid_lock = threading.Lock()
        self.device_mgr = DeviceManager(pdb_module, self)
        self.cron = CronScheduler(self)
        self._cron_counter = 0
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
            if proc.status == READY:
                self._ready_queue.append(pid)  # sigue en RR
            elif proc.status == DEAD:
                self._cleanup(pid)
            elif proc.status in (WAITING, BLOCKED, HALTED):
                pass  # no vuelve a RR hasta que cambie estado
        else:
            # Reconstruir cola si el proceso ya no está
            pass

        return len([p for p in self.processes.values()
                   if p.status not in (DEAD,)])

    def tick_all(self, max_per_process: int = 100) -> int:
        """Ejecutar TODOS los procesos READY (un ciclo completo RR).
        También revisa cron jobs cada 10 ticks."""
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
                if proc.status == READY:
                    self._ready_queue.append(pid)
                    alive += 1
                elif proc.status == DEAD:
                    self._cleanup(pid)
            elif proc and proc.status in (WAITING, BLOCKED, HALTED):
                pass
        self._cron_counter += 1
        if self._cron_counter % 10 == 0:
            self.cron.tick()
        return alive

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
        """Limpiar un proceso muerto de las colas."""
        if pid in self._ready_queue:
            self._ready_queue.remove(pid)

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


class DeviceManager:
    """Gestor de dispositivos I/O. Cada proceso tiene acceso a todos."""

    def __init__(self, pdb_module=None, vm=None):
        self.devices: dict[int, Device] = {}
        self._vm = vm
        self._register_defaults(pdb_module, vm)

    def _register_defaults(self, pdb, vm):
        self.register(ConsoleDevice())
        self.register(DashboardDevice(pdb))
        self.register(LogDevice(pdb))
        self.register(PDBDevice(pdb))
        self.register(HTTPDevice())
        self.register(WebhookDevice())

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
