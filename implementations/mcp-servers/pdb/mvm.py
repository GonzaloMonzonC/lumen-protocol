"""
MVM — M Virtual Machine (LUMEN Process Manager)

Cada "proceso" es un agente M que:
  - Vive en PDB (^PROCESSES y ^STATE)
  - Tiene su propio $J (session_id), stack local, program counter
  - Se ejecuta en slices (cooperativo, no threads)
  - Puede spawnear otros procesos (JOB)
  - Puede recibir mensajes vía cola (mailbox)

La VM es el corazón del thinking server como "hipervisor de agentes M".
"""

import time, json, re, os
from pathlib import Path


class MProcess:
    """Un proceso M vivo. Persiste en PDB entre slices."""
    
    def __init__(self, pid, code, pdb_module, name=""):
        self.pid = pid              # $J (process ID)
        self.name = name            # nombre amigable
        self.code = code            # código M (rutina)
        self.pc = 0                 # program counter (línea actual)
        self.pdb = pdb_module       # referencia a PDB
        self.scope_vars = {}        # variables locales
        self.quit_flag = False
        self.created_at = time.time()
        self.last_run = time.time()
        self.status = "READY"       # READY, RUNNING, HALTED, DEAD
        
        # Cargar estado previo si existe en PDB
        self._load_state()
    
    def _load_state(self):
        """Carga estado desde ^STATE(pid,...)"""
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
        """Guarda estado en ^STATE(pid,...)"""
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
        """Ejecuta un slice del proceso. Retorna True si el proceso sigue vivo."""
        if self.status == "DEAD":
            return False
        if self.status == "HALTED":
            self._save_state()
            return True  # sigue vivo pero dormido
        
        self.status = "RUNNING"
        self.last_run = time.time()
        
        # Dividir código en líneas
        lines = [l.strip() for l in self.code.split("\n") if l.strip()]
        inst_count = 0
        
        from m_light import MEvaluator
        m = MEvaluator(self.pdb)
        
        # Restaurar variables del scope
        m.scope.vars = self.scope_vars
        
        while self.pc < len(lines) and inst_count < max_instructions:
            line = lines[self.pc]
            self.pc += 1
            if not line or line.startswith(";"):
                continue
            
            try:
                m._exec_line(line)
                inst_count += 1
                
                if m._quit_flag:
                    m._quit_flag = False
                    # Si es el final del código, morir
                    if self.pc >= len(lines):
                        self.status = "DEAD"
                        break
            except Exception as e:
                # Error en ejecución — marcar y seguir
                self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "error"], 
                                  "value": f"PC={self.pc}: {e}"})
                self.pc += 1
                inst_count += 1
        
        # Guardar variables de vuelta
        self.scope_vars = dict(m.scope.vars)
        
        if self.pc >= len(lines):
            self.status = "DEAD"  # proceso terminó
        
        self._save_state()
        
        # Enviar mensaje de heartbeat al mailbox
        self.pdb.tool_set({"ns": "STATE", "subs": [self.pid, "mailbox", "heartbeat"], 
                          "value": str(time.time())})
        
        return self.status != "DEAD"


class MVM:
    """M Virtual Machine — gestor de procesos M.
    
    Uso:
      vm = MVM(pdb_tools)
      pid = vm.spawn('S ^TEST(1)="hello"', name="test")
      vm.tick()  # ejecuta un slice de cada proceso
    """
    
    def __init__(self, pdb_module):
        self.pdb = pdb_module
        self.processes = {}  # pid → MProcess
        self._next_pid = 1
        self._load_processes()
    
    def _load_processes(self):
        """Carga procesos existentes de PDB."""
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
                                   name=name_r.get("value", ""))
                    self.processes[pid] = proc
                    if pid >= self._next_pid:
                        self._next_pid = pid + 1
        except:
            pass
    
    def spawn(self, code, name=""):
        """Crea un nuevo proceso M. Retorna el PID ($J)."""
        pid = str(self._next_pid)
        self._next_pid += 1
        
        # Guardar en PDB
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "code"], "value": code})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "name"], "value": name or f"proc_{pid}"})
        self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "spawned_at"], "value": str(time.time())})
        
        proc = MProcess(pid, code, self.pdb, name=name)
        proc._save_state()
        self.processes[pid] = proc
        return pid
    
    def tick(self, max_per_process=100):
        """Ejecuta un slice de cada proceso activo (round-robin)."""
        alive = []
        for pid, proc in list(self.processes.items()):
            if proc.status == "DEAD":
                continue
            proc.step(max_per_process)
            if proc.status != "DEAD":
                alive.append(pid)
        return len(alive)
    
    def kill(self, pid):
        """Mata un proceso."""
        pid = str(pid)
        if pid in self.processes:
            self.processes[pid].status = "DEAD"
            self.processes[pid]._save_state()
            self.pdb.tool_set({"ns": "PROCESSES", "subs": [pid, "status"], "value": "DEAD"})
            return True
        return False
    
    def list_processes(self):
        """Lista todos los procesos y su estado."""
        result = []
        for pid, proc in sorted(self.processes.items()):
            result.append({
                "pid": pid,
                "name": proc.name,
                "status": proc.status,
                "pc": proc.pc,
                "age": time.time() - proc.created_at,
                "last_run": time.time() - proc.last_run if proc.last_run else 0,
                "vars": len(proc.scope_vars),
            })
        return result
    
    def get_process(self, pid):
        """Obtiene un proceso por PID."""
        return self.processes.get(str(pid))
    
    def mailbox_send(self, to_pid, message):
        """Envía un mensaje a la cola de un proceso."""
        to_pid = str(to_pid)
        # Siguiente ID de mensaje
        import random
        next_id = f"msg_{int(time.time()*1000000)}_{random.randint(0,9999)}"
        self.pdb.tool_set({"ns": "STATE", "subs": [to_pid, "mailbox", next_id], 
                          "value": str(message)})
        return next_id
    
    def mailbox_read(self, pid):
        """Lee todos los mensajes pendientes de un proceso."""
        pid = str(pid)
        msgs = []
        m_id = ""
        while True:
            r = self.pdb.tool_order({"ns": "STATE", "subs": [pid, "mailbox", m_id], 
                                     "direction": 1})
            if r.get("value") is None:
                break
            m_id = r["value"]
            if m_id == "heartbeat":
                continue
            val = self.pdb.tool_get({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
            msgs.append({"id": m_id, "content": val.get("value")})
            # Eliminar mensaje leído
            self.pdb.tool_kill({"ns": "STATE", "subs": [pid, "mailbox", m_id]})
        return msgs
