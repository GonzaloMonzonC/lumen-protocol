#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL (MSMSHELL auténtico, MS-DOS style).
v9: PAGE function + ^ quit + INRPT error format + line tracking.

Features MSMSHELL completas:
  > / D> / [ctx] / DEBUG  Prompts
  !N  ?  ??  ?N           Recall & Help
  +  -                     History pages (PGUP/PGDN)
  Page + ^ to quit         Like MSMSHELL PAGE
  INRPT errors             $ZE-style display
  %                        Last result
  o/g/d/s/w/f/i           Aliases
  $ZREF                    Last ^global
  NOMEM                    Degraded safe mode
  INIT/EXIT                Session hooks

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
try: import readline
except: readline = None

TERM_LINES = 24

class MREPL:
    def __init__(self, debug=False, context="", session_id=None):
        self.debug_mode = debug
        self.context = context
        self.running = True
        self.device_mode = False
        self.history_list = []
        self.last_result = None
        self.last_zref = None
        self.session_id = session_id or os.getpid().__str__()
        self.safe_mode = False
        self._cmds = 0
        self._hist_page = 0
        self._y = 0  # $Y line counter for PAGE
        self._setup_completion()
        self._init_session()
        self._load_history_pdb()

    def _setup_completion(self):
        if readline:
            readline.set_completer(self._complete)
            readline.parse_and_bind("tab: complete")

    def _complete(self, text, state):
        NS = ["System","CHANGES","ROUTINE","DDP","Agent","BIJ","docs",
              "TEST","LOGON","MSAJOB","MSASYS","RTHIST","CSFMON"]
        if state == 0: self._matches = [n for n in NS if n.lower().startswith(text.lower())]
        try: return self._matches[state]
        except: return None

    @property
    def prompt(self):
        if self.safe_mode: return "!> "
        if self.debug_mode: return "DEBUG> "
        if self.device_mode: return "D> "
        if self.context: return f"[{self.context}] > "
        return "> "

    # ── PAGE (MSMSHELL: I $Y<21 W ! S X=0 Q) ──
    def _page(self, text):
        """Paging estilo MSMSHELL: --- More --- con ^ para quit."""
        if not text: return
        lines = text.split('\n')
        for i, line in enumerate(lines):
            print(line)
            self._y += 1
            if self._y >= TERM_LINES and i + 1 < len(lines):
                try:
                    r = input("  --- More (RETURN/^ to quit) ---")
                    self._y = 0
                    if r == "^":
                        print("  [<INRPT> Interrupted]")
                        break
                except (KeyboardInterrupt, EOFError):
                    self._y = 0
                    break
        self._y = 0

    # ── Init/Exit ──
    def _init_session(self):
        try:
            from pdb_tools import tool_kill
            tool_kill({"ns": "System", "subs": ["repl", "session", self.session_id]})
        except: self.safe_mode = True
        atexit.register(self._exit_session)

    def _exit_session(self):
        try:
            from pdb_tools import tool_set
            tool_set({"ns": "System", "subs": ["repl", "session", self.session_id], "value": {
                "cmds": self._cmds, "closed": True
            }})
        except: pass

    # ── History PDB ──
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

    # ── NOMEM ──
    def _enter_nomem(self):
        self.safe_mode = True
        self._page("!> NOMEM mode: PDB unavailable, limited commands")

    # ── History pages ──
    def _page_up(self):
        if not self.history_list: return ""
        self._hist_page = min(self._hist_page + 10, len(self.history_list))
        start = max(0, len(self.history_list) - self._hist_page)
        end = min(len(self.history_list), start + 10)
        return "\n".join(f"  {i+1:4d}: {self.history_list[i]}" for i in range(start, end))

    def _page_down(self):
        self._hist_page = max(0, self._hist_page - 10)
        if self._hist_page == 0 and not self.history_list: return "  (top)"
        start = max(0, len(self.history_list) - self._hist_page - 10)
        end = max(0, min(len(self.history_list), start + 10))
        items = [f"  {i+1:4d}: {self.history_list[i]}" for i in range(start, end)]
        return "\n".join(items) if items else "  (top)"

    # ── Exec ──
    def exec(self, cmd):
        if not cmd.strip(): return ""
        self._cmds += 1

        # Shell
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
        if cmd == "zref" or cmd == "$ZREF":
            return f"  {self.last_zref or 'none'}"
        if cmd == "nomem":
            self._enter_nomem(); return "  NOMEM"
        if cmd == "safe":
            self.safe_mode = False; return "  Safe off"

        # History pages
        if cmd == "+": return self._page_up()
        if cmd == "-": return self._page_down()

        # !N
        if cmd.startswith("!"):
            n = cmd[1:].strip()
            rec = self._recall(n if n else None)
            if rec: return f"  {rec}\n  {self.exec(rec)}"
            return "  Not found"

        # ? help
        if cmd == "?": return self._help()
        if cmd == "??": return self._last10()
        if cmd.startswith("?"):
            rest = cmd[1:].strip()
            if rest.isdigit(): return self._show_page(int(rest))
            return self._help_topic(rest)

        # Alias
        AL = {"o":"$O(^","g":"$G(^","d":"$D(^","s":"S ","w":"W ","f":"F ","i":"I "}
        if cmd and cmd[0] in AL: cmd = AL[cmd[0]] + cmd[1:]

        # History
        if not cmd.startswith(("!", "?")): self.history_list.append(cmd)

        # Multi-line
        if self._needs_more(cmd):
            while True:
                try:
                    line = input("  . ")
                    if not line.strip(): break
                    cmd += "\n" + line
                    if not self._needs_more(cmd): break
                except: break

        # $ZREF
        import re
        zm = re.search(r'\^(\w+)', cmd)
        if zm: self.last_zref = f"^{zm.group(1)}"

        # Exec M-Light
        tm = self._get_tools()
        if not tm and self.safe_mode: return "  !> Safe mode"
        try:
            import signal
            class T(Exception): pass
            def h(s,f): raise T()
            signal.signal(signal.SIGALRM, h)
            signal.alarm(10)
            r = tm({"expression": cmd})
            signal.alarm(0)
            if r.get("success"):
                val = r.get("result", "")
                self.last_result = val if val else self.last_result
                if val is not None and val != "":
                    return f"  {str(val)[:500]}"
                return "  (ok)"
            return f"  ❌ {r.get('error', 'eval error')}"
        except T:
            signal.alarm(0)
            return "  ⏱️ Timeout"
        except Exception as e:
            return f"  🔴 <DSCON> {e}"

    def run(self):
        print("╔══════════════════════════════════════╗")
        print("║   M-Light REPL  (MSMSHELL v9)        ║")
        print("║   PAGE + ^ quit  INRPT errors        ║")
        print("╚══════════════════════════════════════╝")
        while self.running:
            try:
                cmd = input(self.prompt)
                if cmd and not cmd.startswith(("!", "?")): self.history_list.append(cmd)
                r = self.exec(cmd)
                if r: self._page(r)
            except KeyboardInterrupt:
                self._page("\n  <INRPT>")
            except EOFError:
                self._save_history_pdb(); print(); break
        self._exit_session()
        self._save_history_pdb()

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
            self._enter_nomem()
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

    def _show_page(self, start):
        end = min(start + 10, len(self.history_list))
        return "\n".join(f"  {i+1:4d}: {self.history_list[i]}" for i in range(max(0, start), end)) or "  Not found"

    def _help_topic(self, topic):
        H = {"$O":"  $O(^ns(sub))  → Next subscript",
             "$G":"  $G(^ns(subs))  → Read value",
             "$D":"  $D(^ns(subs))  → 0/1/10/11",
             "S":"  SET x=val  → Assign",
             "W":"  WRITE expr  → Output",
             "F":"  FOR i=1:1:10  → Loop",
             "I":"  IF cond  → Conditional",
             "PAGE":"  ^ during paging → quit display",
             "$ZREF":"  Last ^global. Type 'zref'",
             "NOMEM":"  !> degraded mode"}
        t = topic.upper()
        if t in H: return H[t]
        for k,v in H.items():
            if t in k: return v
        return f"  No help for '{topic}'"

    def _help(self):
        return """  M-Light REPL v9  (MSMSHELL)
  ════════════════════════════════════
  $O $G $D S W F I Q    — MUMPS
  !N                    — Recall
  +                     — History PgUp
  -                     — History PgDn
  ? ?? ?N ?cmd          — Help
  debug                 — Debug mode
  toggle                — D> prompt
  zref                  — Last ^global
  o/g/d/s/w/f/i         — Aliases
  ^ during paging       — Quit display
  exit                  — Quit

  > $O(^System(""))
  > +           # history page
  > ?$O         # topic help
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
