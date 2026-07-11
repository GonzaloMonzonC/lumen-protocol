#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL (MSMSHELL auténtico, MS-DOS style).
v6: Color, PDB history, % last result, help por comando, aliases.

Features MSMSHELL nativas:
  > $O()        Prompt normal
  D> W $J       Device mode (Ctrl+R toggle)
  [ctx] > ...   Context prompt
  DEBUG> ...    Debug mode
  !N            Recall command
  ? / ?? / ?N   Help system
  %             Last result variable
  o/g/d         Aliases: $O/$G/$D
  
v6 mejoras:
  🎨 Color output (green=ok, red=error, yellow=warn)
  💾 PDB history (^System("repl","history"))
  %  variable con último resultado
  ?comando      Ayuda específica (?for, ?set)

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
try: import readline
except: readline = None

HISTFILE = os.path.expanduser("~/.hermes/mrepl_history")
TERM_LINES = 24
LAST_RESULT = "%"  # como MSMSHELL

# Colores ANSI
C = type('',(),{})()
C.OK = "\033[92m"    # verde
C.WARN = "\033[93m"  # amarillo
C.ERR = "\033[91m"   # rojo
C.RST = "\033[0m"    # reset

NAMESPACES = [
    "System", "CHANGES", "ROUTINE", "DDP", "Agent", "BIJ", "docs",
    "TEST", "LOGON", "MSAJOB", "MSASYS", "RTHIST", "CSFMON", "PDBMAP",
    "CLIMA", "PROCESSES", "STRESS",
]

HELP_TOPICS = {
    "$O": "  $O(^ns(sub))  → Siguiente subscript. Ej: $O(^System(\"\"))",
    "$ORDER": "  $ORDER(^ns(sub))  → Igual que $O. Itera subíndices.",
    "$G": "  $G(^ns(subs))  → Lee valor o \"\" si no existe. Ej: $G(^System(\"config\"))",
    "$GET": "  $GET(^ns(subs))  → Igual que $G.",
    "$D": "  $D(^ns(subs))  → 0=no existe, 1=valor, 10=hijos, 11=ambos",
    "$DATA": "  $DATA(^ns(subs))  → Igual que $D.",
    "S": "  SET x=valor  → Asigna variable local.",
    "SET": "  SET x=valor  → Igual que S.",
    "W": "  WRITE expr  → Muestra valor. W \"Hola\",!,\"Mundo\"",
    "WRITE": "  WRITE expr  → Igual que W.",
    "F": "  FOR i=1:1:10  → Bucle. Usar . para indentar cuerpo.",
    "FOR": "  FOR i=1:1:10  → Igual que F.",
    "I": "  IF cond  → Condicional. I x>5 W \"mayor\"",
    "IF": "  IF cond  → Igual que I.",
    "Q": "  QUIT  → Sale del bucle o rutina.",
    "QUIT": "  QUIT  → Igual que Q.",
}

ALIASES = {
    "o": "$O(^",
    "g": "$G(^", 
    "d": "$D(^",
    "s": "S ",
    "w": "W ",
    "f": "F ",
    "i": "I ",
    "q": "Q ",
}

class Completer:
    def __init__(self):
        self.matches = []
    def complete(self, text, state):
        if state == 0:
            self.matches = [ns for ns in NAMESPACES if ns.lower().startswith(text.lower())]
        try: return self.matches[state]
        except: return None

class MREPL:
    def __init__(self, debug=False, context=""):
        self.debug_mode = debug
        self.context = context
        self.running = True
        self.device_mode = False
        self.history_list = []
        self.last_result = None  # variable %
        self._setup_completion()
        self._load_history_pdb()

    def _setup_completion(self):
        if readline:
            readline.set_completer(Completer().complete)
            readline.parse_and_bind("tab: complete")

    @property
    def prompt(self):
        if self.debug_mode: return f"{C.WARN}DEBUG>{C.RST} "
        if self.device_mode: return f"{C.OK}D>{C.RST} "
        if self.context: return f"{C.OK}[{self.context}] >{C.RST} "
        return f"{C.OK}>{C.RST} "

    # ── History PDB (^System("repl","history")) ──
    def _load_history_pdb(self):
        """Cargar historial desde PDB (MSMSHELL usaba ^MSMSHIST)."""
        try:
            from pdb_tools import tool_order, tool_get
            key = ""
            while True:
                r = tool_order({"ns": "System", "subs": ["repl", "history", key], "direction": 1})
                if not r.get("success") or r.get("value") is None: break
                key = r["value"]
                r2 = tool_get({"ns": "System", "subs": ["repl", "history", key]})
                if r2.get("success") and r2.get("value"):
                    self.history_list.append(r2["value"])
            self.history_list = self.history_list[-200:]  # últimas 200
        except: pass

    def _save_history_pdb(self):
        """Guardar historial en PDB."""
        try:
            from pdb_tools import tool_set, tool_kill
            # Limpiar historial anterior
            tool_kill({"ns": "System", "subs": ["repl", "history"]})
            # Guardar últimas 100
            for i, cmd in enumerate(self.history_list[-100:]):
                tool_set({"ns": "System", "subs": ["repl", "history", str(i+1)], "value": cmd})
        except: pass

    # ── Help por comando ──
    def _help_topic(self, topic):
        topic = topic.upper()
        if topic in HELP_TOPICS:
            return HELP_TOPICS[topic]
        for cmd, desc in HELP_TOPICS.items():
            if topic in cmd or cmd in topic:
                return desc
        return f"  No help for '{topic}'. Try: ?$O, ?$G, ?S, ?F, ?W"

    # ── Format output ──
    def _colorize(self, text, type="ok"):
        if type == "err": return f"{C.ERR}{text}{C.RST}"
        if type == "warn": return f"{C.WARN}{text}{C.RST}"
        return f"{C.OK}{text}{C.RST}"

    def _page(self, text):
        if not text: return
        lines = text.split('\n')
        for i, line in enumerate(lines):
            print(line)
            if (i + 1) % TERM_LINES == 0 and i + 1 < len(lines):
                try: input("  --- More ---")
                except: break

    def _format_error(self, error_msg):
        for code in ["SYNTX", "UNDEF", "DIVIDE"]:
            if code.lower() in str(error_msg).lower():
                return f"  ❌ {self._colorize(f'<{code}>', 'err')}"
        return f"  🔴 {self._colorize(f'<ERROR> {error_msg}', 'err')}"

    # ── Exec ──
    def exec(self, cmd):
        if not cmd.strip(): return ""

        # ── Shell commands ──
        if cmd in ("exit", "quit"):
            self._save_history_pdb()
            self.running = False
            return ""

        if cmd == "debug":
            self.debug_mode = not self.debug_mode
            return f"  Debug: {'ON' if self.debug_mode else 'OFF'}"

        if cmd in ("toggle", "\x12"):
            self.device_mode = not self.device_mode
            return f"  Prompt: {'D>' if self.device_mode else '>'}"

        if cmd.startswith("!"):
            n = cmd[1:].strip()
            recalled = self._recall(n if n else None)
            if recalled: return f"  {recalled}\n  {self.exec(recalled)}"
            return self._colorize("  Not found", "warn")

        if cmd == "?":
            return self._help()
        if cmd == "??":
            return self._last10()
        if cmd.startswith("?") and cmd[1:].strip():
            topic = cmd[1:].strip()
            return self._help_topic(topic)
        if cmd.startswith("?") and cmd[1:].strip().isdigit():
            n = cmd[1:].strip()
            try:
                idx = int(n)
                lines = []
                for i in range(idx, min(idx + 10, len(self.history_list) + 1)):
                    if i <= len(self.history_list):
                        lines.append(f"  {i:4d}: {self.history_list[i-1]}")
                return "\n".join(lines) if lines else self._colorize("  Not found", "warn")
            except: pass

        # Aliases
        if len(cmd) > 0 and cmd[0] in ALIASES and cmd[0] != cmd:
            cmd = ALIASES[cmd[0]] + cmd[1:]

        # History
        if not cmd.startswith(("!", "?")):
            self.history_list.append(cmd)

        # Multi-line
        if self._needs_more(cmd):
            while True:
                try:
                    line = input("  . ")
                    if line.strip() == "" or line.strip().upper() == "Q":
                        break
                    cmd += "\n" + line
                    if not self._needs_more(cmd): break
                except (KeyboardInterrupt, EOFError):
                    break

        # ── Exec M-Light ──
        tool_m_eval = self._get_tools()
        try:
            import signal
            class Timeout(Exception): pass
            def handler(signum, frame): raise Timeout()
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(10)
            result = tool_m_eval({"expression": cmd})
            signal.alarm(0)
            if result.get("success"):
                val = result.get("result", "")
                output = result.get("output", "")
                self.last_result = val  # % variable
                parts = []
                if val is not None and val != "":
                    parts.append(self._colorize(str(val)[:500]))
                if output:
                    parts.append(self._colorize(f"[OUT] {output[:200]}", "warn"))
                if self.debug_mode:
                    parts.append(self._colorize(f"[%={val}]", "warn"))
                r = "\n".join(parts) if parts else self._colorize("(ok)")
                return r
            else:
                return self._format_error(result.get('error', 'eval error'))
        except Timeout:
            signal.alarm(0)
            return self._colorize("⏱️ <TIMEOUT>", "err")
        except Exception as e:
            return self._format_error(str(e))

    def run(self):
        print(f"{C.OK}╔══════════════════════════════════════╗{C.RST}")
        print(f"{C.OK}║   M-Light REPL  (MSMSHELL v6)        ║{C.RST}")
        print(f"{C.OK}║   ?help  !recall  Ctrl+R  aliases    ║{C.RST}")
        print(f"{C.OK}║   % = last result                    ║{C.RST}")
        print(f"{C.OK}╚══════════════════════════════════════╝{C.RST}")
        while self.running:
            try:
                cmd = input(self.prompt)
                if cmd and not cmd.startswith(("!", "?")):
                    self.history_list.append(cmd)
                r = self.exec(cmd)
                if r: self._page(r)
            except KeyboardInterrupt:
                print(f"\n  {self._colorize('<INRPT> Break', 'warn')}")
            except EOFError:
                self._save_history_pdb(); print(); break

    def _needs_more(self, cmd):
        last = cmd.strip().split('\n')[-1].strip()
        if last.startswith("F ") and not any(c in last for c in [".", "D", "S ", "W "]):
            return True
        if last.startswith("I ") and not any(c in last for c in ["S ", "W ", "D ", "Q"]):
            return True
        if last.rstrip().endswith("="): return True
        return False

    def _get_tools(self):
        pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
        from pdb_tools import tool_m_eval
        return tool_m_eval

    def _recall(self, n=None):
        if n is None: return self.history_list[-1] if self.history_list else ""
        try:
            idx = int(n)
            if 1 <= idx <= len(self.history_list): return self.history_list[idx-1]
        except: pass
        return ""

    def _last10(self):
        start = max(0, len(self.history_list) - 10)
        return "\n".join(f"  {i+1:4d}: {self.history_list[i]}" for i in range(start, len(self.history_list))) or "  (no history)"

    def _help(self):
        return """  M-Light REPL v6 — Ayuda rápida
  ════════════════════════════════════
  MUMPS:  $O  $G  $D  SET  WRITE  FOR  IF  QUIT
  Shell:  !N recall  ? help  ?? last 10  ?comando
  Alias:  o=$O(^  g=$G(^  d=$D(^  s=S  w=W  f=F  i=I
  Toggle: Ctrl+R  →  > / D> prompt
  Debug:  debug   →  modo debug
  %             →  último resultado (como MSMSHELL)
  Tab:    ^namespace completion
  Exit:   exit / quit

  > ?$O       → ayuda específica
  > o TEST    → alias: $O(^TEST
  > S x=42    → ejecuta
  > W %       → muestra último resultado
"""

def main():
    debug = "--debug" in sys.argv
    context = ""
    if "--context" in sys.argv:
        idx = sys.argv.index("--context") + 1
        if idx < len(sys.argv): context = sys.argv[idx]
    if "--cmd" in sys.argv:
        idx = sys.argv.index("--cmd") + 1
        if idx < len(sys.argv):
            r = MREPL(); print(r.exec(sys.argv[idx])); return
    MREPL(debug=debug, context=context).run()

if __name__ == "__main__":
    main()
