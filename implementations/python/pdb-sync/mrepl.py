#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL (MSMSHELL auténtico MS-DOS style).
v4: Paging, Toggle, multi-line, MSM error codes.

Features nativas de MSMSHELL:
  > $O()        Prompt normal
  D> W $J       Device mode (Ctrl+R toggle)
  [ctx] > ...   Context prompt
  DEBUG> ...    Debug mode
  !N            Recall command
  ? / ?? / ?N   Help system
  Ctrl+R        Toggle prompt mode
  --- More ---  Paging output > 24 lines

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
try: import readline
except: readline = None

HISTFILE = os.path.expanduser("~/.hermes/mrepl_history")
TERM_LINES = 24
TERM_COLS = 80

NAMESPACES = [
    "System", "CHANGES", "ROUTINE", "DDP", "Agent", "BIJ", "docs",
    "TEST", "LOGON", "MSAJOB", "MSASYS", "RTHIST", "CSFMON", "PDBMAP",
    "CLIMA", "PROCESSES", "STRESS", "COMPARE_TEST",
]

ERROR_CODES = {
    "SYNTX": "Invalid M syntax",
    "UNDEF": "Undefined variable",
    "DIVIDE": "Division by zero",
    "NOMEM": "Out of memory",
    "INRPT": "Interrupted",
    "DSCON": "Device disconnected",
}

class Completer:
    def __init__(self):
        self.matches = []
    def complete(self, text, state):
        if state == 0:
            self.matches = [ns for ns in NAMESPACES if ns.lower().startswith(text.lower())]
        try:
            return self.matches[state]
        except: return None

class MREPL:
    def __init__(self, debug=False, context=""):
        self.debug_mode = debug
        self.context = context
        self.running = True
        self.device_mode = False  # D> prompt
        self.history_list = []
        self.line_count = 0
        self._setup_completion()
        self._load_history()

    def _setup_completion(self):
        if readline:
            readline.set_completer(Completer().complete)
            readline.parse_and_bind("tab: complete")

    @property
    def prompt(self):
        if self.debug_mode: return "DEBUG> "
        if self.device_mode: return "D> "
        if self.context: return f"[{self.context}] > "
        return "> "

    def _load_history(self):
        try:
            if readline and os.path.exists(HISTFILE):
                readline.read_history_file(HISTFILE)
        except: pass
        atexit.register(self._save_history)

    def _save_history(self):
        try:
            os.makedirs(os.path.dirname(HISTFILE), exist_ok=True)
            if readline: readline.write_history_file(HISTFILE)
        except: pass

    def _page(self, text):
        """Paging estilo MSMSHELL: --- More ---"""
        if not text: return
        lines = text.split('\n')
        for i, line in enumerate(lines):
            print(line)
            if (i + 1) % TERM_LINES == 0 and i + 1 < len(lines):
                try:
                    input("  --- More ---")
                except (KeyboardInterrupt, EOFError):
                    print()
                    break

    def _format_error(self, error_msg):
        """$ZE-style error: <ERROR> message"""
        for code, desc in ERROR_CODES.items():
            if code.lower() in str(error_msg).lower():
                return f"  ❌ <{code}> {desc}"
        return f"  ❌ <ERROR> {error_msg}"

    def exec(self, cmd):
        if not cmd.strip():
            return ""

        # ── Comandos del shell ──
        if cmd in ("exit", "quit"):
            self.running = False
            return ""

        if cmd == "debug":
            self.debug_mode = not self.debug_mode
            return f"  Debug mode: {'ON 🐛' if self.debug_mode else 'OFF'}"

        # Ctrl+R toggle device mode
        if cmd == "toggle" or cmd == "\x12":  # \x12 = Ctrl+R
            self.device_mode = not self.device_mode
            return f"  Prompt: {'D>' if self.device_mode else '>'}"

        # !N recall
        if cmd.startswith("!"):
            n = cmd[1:].strip()
            recalled = self._recall(n if n else None)
            if recalled:
                return f"  {recalled}\n  {self.exec(recalled)}"
            return "  Not found"

        # ? help
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

        # History
        if not cmd.startswith(("!", "?")):
            self.history_list.append(cmd)

        # Multi-line: F, S, I incompletos → seguir leyendo
        if self._needs_more(cmd):
            continuation = True
            while continuation:
                try:
                    line = input("  > ")
                    if line.rstrip().endswith("Q") or line.rstrip() == "":
                        continuation = False
                    cmd += "\n" + line
                    continuation = self._needs_more(cmd)
                except (KeyboardInterrupt, EOFError):
                    continuation = False

        # ── M-Light ──
        tool_m_eval = self._get_tools()
        try:
            import signal
            class TimeoutError(Exception): pass
            def handler(signum, frame): raise TimeoutError("Interrupted")
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(10)  # 10s timeout

            try:
                result = tool_m_eval({"expression": cmd})
                signal.alarm(0)
                if result.get("success"):
                    val = result.get("result", "")
                    output = result.get("output", "")
                    # Mostrar WRITE output (como MSMSHELL)
                    write_output = ""
                    if output:
                        write_output = f"  [OUT] {output[:200]}"
                    if self.debug_mode:
                        parts = []
                        if val is not None and val != "": parts.append(f"= {val}")
                        r = "  " + "  ".join(parts) if parts else "  (ok)"
                        return (r + "\n" + write_output) if write_output else r
                    if val is not None and val != "":
                        val_str = str(val)
                        if len(val_str) > 500: val_str = val_str[:500] + "..."
                        r = f"  {val_str}"
                        return (r + "\n" + write_output) if write_output else r
                    return write_output if write_output else "  (ok)"
                else:
                    return self._format_error(result.get('error', 'eval error'))
            except TimeoutError:
                signal.alarm(0)
                return "  ⏱️ <TIMEOUT> Expression took >10s"
            except Exception as e:
                signal.alarm(0)
                return f"  🔴 <DSCON> {e}"
        except Exception as e:
            return f"  🔴 <ERROR> {e}"

    def run(self):
        print("╔══════════════════════════════════════╗")
        print("║   M-Light REPL  (MSMSHELL v4)        ║")
        print("║   ? help  ! recall  Ctrl+R toggle    ║")
        print("║   Tab completion for ^namespaces     ║")
        print("╚══════════════════════════════════════╝")
        while self.running:
            try:
                cmd = input(self.prompt)
                if cmd and not cmd.startswith(("!", "?")):
                    self.history_list.append(cmd)
                result = self.exec(cmd)
                if result:
                    self._page(result)
            except KeyboardInterrupt:
                print("\n  <INRPT> Break")
            except EOFError:
                print()
                break

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

    def _needs_more(self, cmd):
        """Detectar si el comando necesita más líneas (multi-line)."""
        last_line = cmd.strip().split('\n')[-1].strip()
        # FOR sin cuerpo completo
        if last_line.startswith("F ") and not any(c in last_line for c in [".", "D", "S ", "W "]):
            return True
        # DO sin argumento completo
        if last_line.startswith("D ") and not last_line.rstrip().endswith("."):
            return True
        # IF sin acción
        if last_line.startswith("I ") and not any(c in last_line for c in ["S ", "W ", "D ", "Q"]):
            return True
        # SET incompleto
        if last_line.rstrip().endswith("="):
            return True
        return False

    def _get_tools(self):
        pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
        from pdb_tools import tool_m_eval
        return tool_m_eval

    def _help(self):
        return """  M-Light REPL  (MSMSHELL-style v4)
  ════════════════════════════════════
  MUMPS:  $O  $G  $D  S  W  F
  Shell:  !N recall  ? help  ?? last 10
  Toggle: Ctrl+R or 'toggle' — prompt > / D>
  Multi:  Incomplete F/I/D lines continue
  Debug:  'debug' — toggle debug mode
  Tab:    Complete ^namespace names
  Exit:   exit / quit

  > $O(^System(""))
  > S x=5  W x
  > toggle
  D> W "device mode"
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
    r = MREPL(debug=debug, context=context)
    r.run()

if __name__ == "__main__":
    main()
