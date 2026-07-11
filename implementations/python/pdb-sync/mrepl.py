#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL (MSMSHELL auténtico, MS-DOS style).

Inspirado en MSMSHELL (172 líneas) de MSM para MS-DOS.

Experiencia nativa:
  > $O(^TEST(""))          ← Prompt simple
  D> W $J                   ← Device mode prompt
  [TEST] > S x=5            ← UCI context prompt
  DEBUG> S x=$O(^TEST("")) ← Debug mode

  !    → Recall last command
  !5   → Recall command #5
  ?    → Help
  ??   → Last 10 commands
  debug → Toggle debug mode

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
from datetime import datetime

HISTFILE = os.path.expanduser("~/.hermes/mrepl_history")
HIST_MAX = 9999

class MREPL:
    def __init__(self, debug=False, context=""):
        self.debug_mode = debug
        self.context = context  # UCI/namespace context
        self.running = True
        self.history_list = []
        self.hist_index = 0
        self._load_history()

    # ── Prompt ──
    @property
    def prompt(self):
        if self.debug_mode:
            return "DEBUG> "
        if self.context:
            return f"[{self.context}] > "
        return "> "

    # ── History (^MSMSHIST style) ──
    def _load_history(self):
        try:
            with open(HISTFILE) as f:
                self.history_list = [l.rstrip('\n') for l in f.readlines() if l.strip()]
                self.history_list = self.history_list[-HIST_MAX:]
        except: pass
        atexit.register(self._save_history)

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(HISTFILE), exist_ok=True)
            with open(HISTFILE, 'w') as f:
                for cmd in self.history_list[-500:]:
                    f.write(cmd + '\n')
        except: pass

    def _add_to_history(self, cmd):
        if not cmd or cmd.startswith(('!', '?')):
            return
        if self.history_list and self.history_list[-1] == cmd:
            return  # no duplicados
        self.history_list.append(cmd)
        self.hist_index = len(self.history_list)

    def _recall(self, n=None):
        """! o !N — recordar comando."""
        if n is None:
            return self.history_list[-1] if self.history_list else ""
        try:
            idx = int(n)
            if 1 <= idx <= len(self.history_list):
                return self.history_list[idx - 1]
        except: pass
        return ""

    def _last10(self):
        """?? — últimos 10 comandos."""
        lines = []
        start = max(0, len(self.history_list) - 10)
        for i in range(start, len(self.history_list)):
            lines.append(f"  {i+1:4d}: {self.history_list[i]}")
        return "\n".join(lines) if lines else "  (no history)"

    # ── M-Light execution ──
    def _get_tools(self):
        pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
        from pdb_tools import tool_m_eval
        return tool_m_eval

    def exec(self, cmd):
        if not cmd.strip():
            return ""

        # MSMSHELL special commands
        if cmd == "exit" or cmd == "quit":
            self.running = False
            return ""
        if cmd == "debug":
            self.debug_mode = not self.debug_mode
            st = "ON 🐛" if self.debug_mode else "OFF"
            return f"  Debug mode: {st}"
        if cmd.startswith("!"):
            n = cmd[1:].strip()
            recalled = self._recall(n if n else None)
            if recalled:
                print(f"  {recalled}")
                return self.exec(recalled)
            return "  Not found"
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

        self._add_to_history(cmd)

        # Ejecutar M-Light
        try:
            tool_m_eval = self._get_tools()
            result = tool_m_eval({"expression": cmd})
            if result.get("success"):
                val = result.get("result", "")
                output = ""
                if hasattr(result, 'get') and 'output' in result:
                    output = result.get('output', '')
                if self.debug_mode:
                    parts = []
                    if output: parts.append(f"[OUT] {output[:60]}")
                    if val is not None and val != '': parts.append(f"= {val}")
                    return "  " + "  ".join(parts) if parts else "  (ok)"
                return str(val) if val is not None and val != '' else (output if output else "  (ok)")
            else:
                return f"  ❌ {result.get('error', 'eval error')}"
        except Exception as e:
            return f"  🔴 ERROR: {e}"

    def run(self):
        print("╔═══════════════════════════════════╗")
        print("║   M-Light REPL  (MSMSHELL)        ║")
        print("║   Type ? for help                  ║")
        print("╚═══════════════════════════════════╝")
        while self.running:
            try:
                cmd = input(self.prompt)
                result = self.exec(cmd)
                if result:
                    print(result)
            except KeyboardInterrupt:
                print("\n  Break")
            except EOFError:
                print()
                break

    def _help(self):
        return """  M-Light REPL (MSMSHELL-style)
  ═══════════════════════════════
  MUMPS commands:
    $O(^ns(""))    $ORDER — iterate
    $G(^ns(sub))   $GET — read value  
    $D(^ns(sub))   $DATA — check existence
    S x=value      SET — assign
    W expr         WRITE — output

  Shell commands:
    !           Recall last command
    !N          Recall command #N
    ?           This help
    ??          Last 10 commands
    ?N          List from N
    debug       Toggle debug mode
    exit/quit   Exit REPL

  Examples:
    > $O(^System(""))
    > $G(^ROUTINE("%ET",1))
    > F i=1:1:5 W i
"""

def main():
    import sys
    debug = "--debug" in sys.argv
    
    if "--cmd" in sys.argv:
        idx = sys.argv.index("--cmd") + 1
        if idx < len(sys.argv):
            r = MREPL()
            print(r.exec(sys.argv[idx]))
        return
    
    r = MREPL(debug=debug)
    r.run()

if __name__ == "__main__":
    main()
