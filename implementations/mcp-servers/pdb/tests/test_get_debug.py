"""Test $GET multi-nivel — debug paso a paso."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from m_light import MEvaluator
import pdb_tools

class DebugEval(MEvaluator):
    def _resolve(self, token):
        m = re.match(r'\$(?:GET|G)\s*\(\^(\w+)\((.+?)\)\s*\)', token)
        if m:
            ns = m.group(1)
            subs = self._parse_subs(m.group(2))
            print(f"  $GET MATCH! ns={ns}, subs={subs}")
            r = self.pdb.tool_get({"ns": ns, "subs": subs})
            print(f"  tool_get -> {r}")
            return r.get("value")
        # Fall through to parent
        return super()._resolve(token)

m = DebugEval(pdb_tools)
val = m.eval_expr('$G(^CLIMA("Tarragona","2026-07-05"))')
print(f"eval_expr: {val}")
