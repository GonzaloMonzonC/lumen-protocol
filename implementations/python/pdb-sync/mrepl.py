#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL (MSMSHELL auténtico, MS-DOS style).
v7: INIT/EXIT hooks, safe mode, $ZREF.

Features MSMSHELL nativas:
  > / D> / [ctx]> / DEBUG>  Prompts
  !N            Recall command
  ? / ?? / ?N   Help system
  %             Last result variable
  Ctrl+R        Toggle prompt
  o/g/d/s/w/f/i Aliases
  $ZREF         Last global referenced
  INIT/EXIT     Session hooks (like MSMSHELL)
  Safe mode     PDB unavailable → minimal mode

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
try: import readline
except: readline = None

HISTFILE = os.path.expanduser("~/.hermes/mrepl_history")

class MREPL:
    def __init__(self, debug=False, context="", session_id=None):
        self.debug_mode = debug
        self.context = context
        self.running = True
        self.device_mode = False
        self.history_list = []
        self.last_result = None
        self.last_zref = None
        self.session_id = session_id or f"repl_{os.getpid()}"
        self.safe_mode = False
        self._cmds = 0
        self._setup_completion()
        self._init_session()
        self._load_history_pdb()

    def _setup_completion(self):
        if readline:
            readline.set_completer(self._complete)
            readline.parse_and_bind("tab: complete")

    def _complete(self, text, state):
        NAMESPACES = ["System","CHANGES","ROUTINE","DDP","Agent","BIJ","docs",
                      "TEST","LOGON","MSAJOB","MSASYS","RTHIST","CSFMON","PDBMAP"]
        if state == 0:
            self._matches = [ns for ns in NAMESPACES if ns.lower().startswith(text.lower())]
        try: return self._matches[state]
        except: return None

    @property
    def prompt(self):
        if self.safe_mode: return "!> "
        if self.debug_mode: return "DEBUG> "
        if self.device_mode: return "D> "
        if self.context: return f"[{self.context}] > "
        return "> "

    # ── INIT/EXIT hooks (MSMSHELL: INIT()/EXIT()) ──
    def _init_session(self):
        """INIT() — Limpiar historial previo y preparar sesión."""
        try:
            from pdb_tools import tool_kill
            tool_kill({"ns": "System", "subs": ["repl", "session", self.session_id]})
        except:
            self.safe_mode = True
        atexit.register(self._exit_session)

    def _exit_session(self):
        """EXIT() — Guardar estado y limpiar."""
        try:
            from pdb_tools import tool_set
            tool_set({"ns": "System", "subs": ["repl", "session", self.session_id], "value": {
                "cmds": self._cmds, "closed": True
            }})
        except: pass

    # ── History ──
    def _load_history_pdb(self):
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
            self.history_list = self.history_list[-200:]
        except: pass

    def _save_history_pdb(self):
        try:
            from pdb_tools import tool_set, tool_kill
            tool_kill({"ns": "System", "subs": ["repl", "history"]})
            for i, cmd in enumerate(self.history_list[-100:]):
                tool_set({"ns": "System", "subs": ["repl", "history", str(i+1)], "value": cmd})
        except: pass

    # ── Commands ──
    def exec(self, cmd):
        if not cmd.strip(): return ""
        self._cmds += 1

        # Shell commands
        if cmd in ("exit", "quit"):
            self._save_history_pdb()
            self._exit_session()
            self.running = False
            return ""
        if cmd == "debug":
            self.debug_mode = not self.debug_mode
            return f"  Debug: {'ON' if self.debug_mode else 'OFF'}"
        if cmd in ("toggle", "\x12"):
            self.device_mode = not self.device_mode
            return f"  Prompt: {'D>' if self.device_mode else '>'}"
        if cmd == "$ZREF" or cmd == "zref":
            return f"  {self.last_zref or '(none)'}"

        # ! recall
        if cmd.startswith("!"):
            n = cmd[1:].strip()
            recalled = self._recall(n if n else None)
            if recalled: return f"  {recalled}\n  {self.exec(recalled)}"
            return "  Not found"

        # ? help
        if cmd == "?": return self._help()
        if cmd == "??": return self._last10()
        if cmd.startswith("?") and cmd[1:].strip():
            return self._help_topic(cmd[1:].strip())

        # Alias
        ALIASES = {"o":"$O(^","g":"$G(^","d":"$D(^","s":"S ","w":"W ","f":"F ","i":"I ","q":"Q "}
        if cmd and cmd[0] in ALIASES:
            cmd = ALIASES[cmd[0]] + cmd[1:]

        # History
        if not cmd.startswith(("!", "?")):
            self.history_list.append(cmd)

        # Multi-line
        if self._needs_more(cmd):
            while True:
                try:
                    line = input("  . ")
                    if not line.strip(): break
                    cmd += "\n" + line
                    if not self._needs_more(cmd): break
                except (KeyboardInterrupt, EOFError): break

        # Detect $ZREF: extraer ^GLOBAL del comando
        import re
        zref_m = re.search(r'\^(\w+)', cmd)
        if zref_m: self.last_zref = f"^{zref_m.group(1)}"

        # M-Light eval
        tool_m_eval = self._get_tools()
        if not tool_m_eval and self.safe_mode:
            return "  !> Safe mode: PDB unavailable"
        try:
            import signal
            class TimeoutEx(Exception): pass
            def handler(s, f): raise TimeoutEx()
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(10)
            result = tool_m_eval({"expression": cmd})
            signal.alarm(0)
            if result.get("success"):
                val = result.get("result", "")
                self.last_result = val if val != "" else self.last_result
                if val is not None and val != "":
                    return f"  {str(val)[:500]}"
                return "  (ok)"
            return f"  ❌ {result.get('error', 'eval error')}"
        except TimeoutEx:
            signal.alarm(0)
            return "  ⏱️ Timeout"
        except Exception as e:
            return f"  🔴 <DSCON> {e}"

    def run(self):
        print("╔══════════════════════════════════════╗")
        print("║   M-Light REPL  (MSMSHELL v7)        ║")
        print("║   ?help  !recall  aliases  $ZREF     ║")
        print("╚══════════════════════════════════════╝")
        while self.running:
            try:
                cmd = input(self.prompt)
                if cmd and not cmd.startswith(("!", "?")):
                    self.history_list.append(cmd)
                r = self.exec(cmd)
                if r: print(r)
            except KeyboardInterrupt:
                print("\n  <INRPT>")
            except EOFError:
                self._save_history_pdb(); print(); break

    def _needs_more(self, cmd):
        last = cmd.strip().split('\n')[-1].strip()
        if last.startswith("F ") and not any(c in last for c in [".","D","S ","W "]): return True
        if last.rstrip().endswith("="): return True
        return False

    def _get_tools(self):
        try:
            pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
            if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
            from pdb_tools import tool_m_eval
            return tool_m_eval
        except:
            self.safe_mode = True
            return None

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

    def _help_topic(self, topic):
        HELP = {
            "$O": "  $O(^ns(sub))  → Next subscript. $O(^System(\"\"))",
            "$G": "  $G(^ns(subs))  → Read value or \"\". $G(^System(\"config\"))",
            "$D": "  $D(^ns(subs))  → 0/1/10/11 existence check",
            "S": "  SET x=val  → Assign local variable",
            "W": "  WRITE expr  → Output value. W \"Hello\",!,\"World\"",
            "F": "  FOR i=1:1:10  → Loop. Use . for body",
            "I": "  IF cond  → Conditional. I x>5 W \"big\"",
            "Q": "  QUIT  → Exit loop or routine",
            "$ZREF": "  Last ^global referenced. Type 'zref' to see it",
        }
        t = topic.upper()
        if t in HELP: return HELP[t]
        for k, v in HELP.items():
            if t in k: return v
        return f"  No help for '{topic}'"

    def _help(self):
        return """  M-Light REPL v7  (MSMSHELL)
  ════════════════════════════════════
  Commands: $O $G $D S W F I Q
  Shell:    !N  ?  ??  ?topic  debug  toggle
  Aliases:  o=$O(^ g=$G(^ d=$D(^ s=S w=W f=F i=I
  Vars:     % = last result, $ZREF = last global
  Exit:     exit / quit

  > $O(^System(""))    → iterate
  > S x=42             → assign
  > W %                → 42
  > zref               → ^System
"""

def main():
    import sys
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
