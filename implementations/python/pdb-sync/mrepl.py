#!/usr/bin/env python3
"""
mrepl.py — M-Light REPL mejorado con MSMSHELL features.

Inspirado en MSMSHELL (172 líneas) de MSM.

3 features de Zalo:
  1. Historial persistente en ^System("repl", "history")
  2. Error handling que no mate la sesión
  3. Modo debug paso a paso

Uso:
  python mrepl.py                  # REPL interactivo
  python mrepl.py --debug          # REPL en modo debug
  python mrepl.py --cmd "W $O(...)"  # Ejecutar comando único

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, atexit
try: import readline
except: readline = None

HISTFILE = os.path.expanduser("~/.hermes/mrepl_history")

class MREPL:
    def __init__(self, debug=False):
        self.history = []
        self.debug_mode = debug
        self.running = True
        self.variables = {}  # variables locales del REPL
        self._load_history()

    def _load_history(self):
        """Cargar historial persistente."""
        try:
            if os.path.exists(HISTFILE):
                readline.read_history_file(HISTFILE)
        except:
            pass
        atexit.register(lambda: self._save_history())

    def _save_history(self):
        """Guardar historial persistente."""
        try:
            os.makedirs(os.path.dirname(HISTFILE), exist_ok=True)
            readline.write_history_file(HISTFILE)
        except:
            pass

    def _get_tools(self):
        """Obtener tools de PDB."""
        pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
        if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
        from pdb_tools import tool_m_eval, tool_get, tool_set, tool_order
        return tool_m_eval, tool_get, tool_set, tool_order

    def exec(self, cmd):
        """Ejecutar un comando M con try/except (Feature 2: error handling)."""
        if not cmd.strip():
            return ""
        
        tool_m_eval, tool_get, tool_set, tool_order = self._get_tools()
        
        # Comandos especiales del REPL
        if cmd == "exit" or cmd == "quit":
            self.running = False
            return "👋 Bye!"
        elif cmd == "debug":
            self.debug_mode = not self.debug_mode
            return f"Debug mode: {'ON' if self.debug_mode else 'OFF'}"
        elif cmd == "history":
            return self._show_history()
        elif cmd.startswith("vars"):
            return str(self.variables)
        elif cmd.startswith("help"):
            return self._help()
        
        # Ejecutar M-Light
        try:
            result = tool_m_eval({"expression": cmd})
            if result.get("success"):
                val = result.get("result", "")
                output = result.get("output", "")
                if self.debug_mode and output:
                    return f"[OUT] {output}\n= {val}"
                return str(val) if val else output if output else "(ok)"
            else:
                return f"❌ {result.get('error', 'eval error')}"
        except Exception as e:
            return f"🔴 ERROR: {e}"
    
    def run(self):
        """Bucle REPL principal (Feature 3: debug mode)."""
        print("╔═══════════════════════════════════╗")
        print("║   M-Light REPL (MSMSHELL style)   ║")
        print("╚═══════════════════════════════════╝")
        print("Type 'help' for commands, 'exit' to quit")
        if self.debug_mode:
            print("Mode: DEBUG 🐛")
        
        while self.running:
            try:
                prefix = "M! " if self.debug_mode else "M> "
                cmd = input(prefix)
                if cmd:
                    result = self.exec(cmd)
                    if result and result != "(ok)":
                        print(result)
            except KeyboardInterrupt:
                print("\n👋 Bye!")
                break
            except EOFError:
                print("\n👋 Bye!")
                break
    
    def _show_history(self):
        """Feature 1: Mostrar historial."""
        try:
            h = []
            for i in range(readline.get_current_history_length()):
                try:
                    h.append(f"  {i}: {readline.get_history_item(i)}")
                except:
                    pass
            return "\n".join(h[-20:]) if h else "(empty)"
        except:
            return "(history unavailable)"
    
    def _help(self):
        return """M-Light REPL commands:
  exit/quit  → Salir
  debug      → Toggle debug mode
  history    → Show command history
  vars       → Show local variables
  help       → This help
  
  Any M-Light expression:
    $O(^ns(""))
    $G(^ns(sub))
    $D(^ns(sub))
    S x=1
    W x
"""

def main():
    import sys
    debug = "--debug" in sys.argv
    
    if "--cmd" in sys.argv:
        idx = sys.argv.index("--cmd") + 1
        if idx < len(sys.argv):
            repl = MREPL(debug=False)
            print(repl.exec(sys.argv[idx]))
        return
    
    repl = MREPL(debug=debug)
    repl.run()

if __name__ == "__main__":
    main()
