#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL (MSMSHELL auténtico, MS-DOS style).

Inspirado en MSMSHELL (172 líneas) de MSM para MS-DOS.
v3: Tab completion, mejor display de errores, history persistente.

Experiencia nativa:
  > $O(^TEST(""))          → A1
  D> W $J                   → Device mode prompt
  DEBUG> S x=5              → Debug mode
  !    → Recall last command   (como MSMSHELL)
  !5   → Recall command #5
  ?    → Help
  ??   → Last 10 commands
  debug → Toggle debug mode
  <TAB> → Complete namespace names

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
try: import readline
except: readline = None

HISTFILE = os.path.expanduser("~/.hermes/mrepl_history")
HIST_MAX = 9999

# Namespaces conocidos para tab completion
NAMESPACES = [
    "System", "CHANGES", "ROUTINE", "DDP", "Agent", "BIJ",
    "docs", "TEST", "LOGON", "MSAJOB", "MSASYS", "RTHIST",
    "CSFMON", "PDBMAP", "CLIMA", "RTHIST", "PROCESSES",
    "^System", "^CHANGES", "^ROUTINE", "^DDP", "^Agent",
    "^BIJ", "^docs", "^TEST", "^LOGON",
]

class Completer:
    """Tab completion para namespaces."""
    def __init__(self):
        self.matches = []
    def complete(self, text, state):
        if state == 0:
            if text.startswith("^") or text.startswith("$"):
                self.matches = [ns for ns in NAMESPACES if ns.lower().startswith(text.lower())]
            else:
                self.matches = [ns for ns in NAMESPACES if ns.lower().startswith(text.lower())]
        try:
            return self.matches[state]
        except IndexError:
            return None

class MREPL:
    def __init__(self, debug=False, context=""):
        self.debug_mode = debug
        self.context = context
        self.running = True
        self.history_list = []
        self._setup_completion()
        self._load_history()

    def _setup_completion(self):
        """Tab completion (MSMSHELL no tenía, pero es mejora moderna)."""
        try:
            readline.set_completer(Completer().complete)
            readline.parse_and_bind("tab: complete")
        except: pass

    @property
    def prompt(self):
        if self.debug_mode:
            return "DEBUG> "
        if self.context:
            return f"[{self.context}] > "
        return "> "

    def _load_history(self):
        try:
            if os.path.exists(HISTFILE):
                readline.read_history_file(HISTFILE)
        except: pass
        atexit.register(self._save_history)

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(HISTFILE), exist_ok=True)
            readline.write_history_file(HISTFILE)
        except: pass

    def _recall(self, n=None):
        if n is None:
            return self.history_list[-1] if self.history_list else ""
        try:
            idx = int(n)
            if 1 <= idx <= len(self.history_list):
                return self.history_list[idx - 1]
        except: pass
        return ""

    def _last10(self):
        start = max(0, len(self.history_list) - 10)
        lines = []
        for i in range(start, len(self.history_list)):
            lines.append(f"  {i+1:4d}: {self.history_list[i]}")
        return "\n".join(lines) if lines else "  (no history)"

    def _get_tools(self):
        pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
        from pdb_tools import tool_m_eval
        return tool_m_eval

    def exec(self, cmd):
        if not cmd.strip():
            return ""

        # ── MSMSHELL special commands ──
        if cmd in ("exit", "quit"):
            self.running = False
            return ""
        if cmd == "debug":
            self.debug_mode = not self.debug_mode
            return f"  Debug mode: {'ON 🐛' if self.debug_mode else 'OFF'}"

        # !N recall — como MSMSHELL: muestra y ejecuta
        if cmd.startswith("!"):
            n = cmd[1:].strip()
            recalled = self._recall(n if n else None)
            if recalled:
                return f"  {recalled}\n  {self.exec(recalled)}"
            return "  Not found"

        # ? help system (como MSMSHELL: ?, ??, ?N)
        if cmd == "?":
            return self._help()
        if cmd == "??":
            return self._last10()
        if cmd.startswith("?") and cmd[1:].strip():
            n = cmd[1:].strip()
            try:
                idx = int(n)
                lines = []
                for i in range(idx, min(idx + 10, len(self.history_list) + 1)):
                    if i <= len(self.history_list):
                        lines.append(f"  {i:4d}: {self.history_list[i-1]}")
                return "\n".join(lines) if lines else "  Not found"
            except: pass

        # Añadir a history
        if not cmd.startswith(("!", "?")):
            self.history_list.append(cmd)

        # ── Ejecutar M-Light (con $ZE-style error display) ──
        tool_m_eval = self._get_tools()
        try:
            result = tool_m_eval({"expression": cmd})
            if result.get("success"):
                val = result.get("result", "")
                output = ""
                if hasattr(result, 'get') and 'output' in result:
                    output = result.get('output', '')
                
                if self.debug_mode:
                    parts = []
                    if val is not None and val != '': 
                        if isinstance(val, str) and len(val) > 200:
                            parts.append(f"= {val[:200]}...")
                        else:
                            parts.append(f"= {val}")
                    return "  " + "  ".join(parts) if parts else "  (ok)"
                else:
                    if val is not None and val != '':
                        if isinstance(val, str) and len(val) > 500:
                            return f"  {val[:500]}..."
                        return f"  {val}"
                    return "  (ok)"
            else:
                error = result.get('error', 'eval error')
                return f"  ❌ <ERROR> {error}"
        except Exception as e:
            return f"  🔴 <DSCON> {e}"

    def run(self):
        print("╔══════════════════════════════════════╗")
        print("║     M-Light REPL  (MSMSHELL v3)      ║")
        print("║     Type ? for help                   ║")
        print("║     Tab completion for ^namespaces    ║")
        print("╚══════════════════════════════════════╝")
        while self.running:
            try:
                cmd = input(self.prompt)
                self._add_to_history(cmd) if not cmd.startswith(('!', '?')) else None
                result = self.exec(cmd)
                if result:
                    print(result)
            except KeyboardInterrupt:
                print("\n  <INRPT> Break")
            except EOFError:
                print()
                break
            except Exception as e:
                print(f"  🔴 <ERROR> {e}")

    def _add_to_history(self, cmd):
        if cmd and not cmd.startswith(('!', '?')):
            self.history_list.append(cmd)

    def _help(self):
        return """  M-Light REPL  (MSMSHELL-style)
  ════════════════════════════════════
  MUMPS commands:
    $O(^ns(""))     $ORDER   iterate subscripts
    $G(^ns(sub))    $GET     read value
    $D(^ns(sub))    $DATA    check existence
    S x=value       SET      assign variable
    W expr          WRITE    output text
    F i=1:1:n       FOR      loop

  Shell:
    !               Recall last command
    !N              Recall command #N
    ?               This help
    ??              Last 10 commands
    ?N              List from N
    debug           Toggle debug mode
    <TAB>           Complete ^namespace
    exit/quit       Exit REPL

  Examples:
    > $O(^System(""))
    > $G(^ROUTINE("%ET",1))
    > S x=5  W x
"""

def main():
    debug = "--debug" in sys.argv
    
    if "--cmd" in sys.argv:
        idx = sys.argv.index("--cmd") + 1
        if idx < len(sys.argv):
            r = MREPL()
            print(r.exec(sys.argv[idx]))
        return
    
    context = ""
    if "--context" in sys.argv:
        idx = sys.argv.index("--context") + 1
        if idx < len(sys.argv):
            context = sys.argv[idx]
    
    r = MREPL(debug=debug, context=context)
    r.run()

if __name__ == "__main__":
    main()
