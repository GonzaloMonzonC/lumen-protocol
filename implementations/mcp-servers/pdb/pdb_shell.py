#!/usr/bin/env python3
"""
PDB Shell — Interactive CLI for PDB (Process Database)
=======================================================

Usage:
    python pdb_shell.py                    # Interactive mode
    python pdb_shell.py --json             # JSON output mode
    python pdb_shell.py -c "$G(^STATE("global:objective:goal_71","title"))"  # One-shot

Commands (interactive):
    $G(^NS(subs))          — Get value
    $O(^NS(subs),dir)      — Order (next subscript), dir=1 or -1
    $D(^NS(subs))          — Data check (0/1/10/11)
    SET ^NS(subs)=val      — Set value
    KILL ^NS(subs)         — Kill subtree
    ZW ^NS(subs)           — Write with children (like ZWRITE)
    ZWR ^NS(subs)          — Full ZWRITE
    D ^%GL [NS] [(range)]  — Global listing
    D ^%SS                 — System status
    HELP [command]         — Help
    EXIT / QUIT / EOF      — Exit
    SQL: query             — Run SQL on _globals
"""

from __future__ import annotations
import argparse, json, os, sys, time, shutil
from pathlib import Path

# ── PDB Setup ────────────────────────────────────────────────────────────
# Import pdb_tools directly from the same directory
_pdb_dir = Path(__file__).resolve().parent
if str(_pdb_dir) not in sys.path:
    sys.path.insert(0, str(_pdb_dir))

import importlib.util, threading
_spec = importlib.util.spec_from_file_location("pdb_tools", _pdb_dir / "pdb_tools.py")
if _spec and _spec.loader:
    pdb_tools = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(pdb_tools)
    sys.modules["pdb_tools"] = pdb_tools  # M-Light needs this
else:
    print("ERROR: Cannot load pdb_tools.py", file=sys.stderr)
    sys.exit(1)

# pdb_tools is now imported — cache handler references
HANDLERS = pdb_tools.HANDLERS
_get_db_path = pdb_tools._get_db_path

# ── ANSI Colors ──────────────────────────────────────────────────────────
if os.name == "nt" and not os.environ.get("TERM"):
    _HAS_COLOR = False
else:
    _HAS_COLOR = True

def _c(code: str, text: str) -> str:
    if _HAS_COLOR:
        return f"\033[{code}m{text}\033[0m"
    return text

_BOLD = lambda t: _c("1", t)
_GREEN = lambda t: _c("32", t)
_YELLOW = lambda t: _c("33", t)
_BLUE = lambda t: _c("34", t)
_MAGENTA = lambda t: _c("35", t)
_CYAN = lambda t: _c("36", t)
_RED = lambda t: _c("31", t)
_DIM = lambda t: _c("2", t)
_REV = lambda t: _c("7", t)

# ── Terminal Size ────────────────────────────────────────────────────────
def _term_width() -> int:
    try:
        return shutil.get_terminal_size().columns or 80
    except Exception:
        return 80

def _term_height() -> int:
    try:
        return shutil.get_terminal_size().lines or 24
    except Exception:
        return 24

# ── Pagination ───────────────────────────────────────────────────────────
class Pager:
    """Simple pager: prints lines, pauses every page_len lines on Enter."""
    def __init__(self, page_len: int = 0):
        self.page_len = page_len or (_term_height() - 3)
        self._lines = 0
        self._page = 0

    def write(self, line: str = ""):
        print(line)
        self._lines += 1
        if self._lines >= self.page_len:
            self._page += 1
            try:
                input(_DIM(f"  [Page {self._page} — Enter to continue, Ctrl+C to quit] "))
            except (KeyboardInterrupt, EOFError):
                raise StopIteration()
            self._lines = 0

# ── Global Namespace Walker ──────────────────────────────────────────────
def _list_namespaces() -> list[str]:
    """Return sorted list of PDB namespaces."""
    try:
        schema = HANDLERS.get("schema")
        if schema:
            result = schema({})
            if isinstance(result, dict) and "namespaces" in result:
                return sorted([ns["ns"] for ns in result["namespaces"]])
    except Exception:
        pass
    # Fallback: SQL
    try:
        conn = pdb_tools._get_conn()
        cur = conn.execute("SELECT DISTINCT ns FROM _globals ORDER BY ns")
        return [row["ns"] for row in cur.fetchall()]
    except Exception:
        return []

def _complete_namespace(text: str) -> list[str]:
    """Tab-complete namespace names."""
    namespaces = _list_namespaces()
    if not text:
        return namespaces
    return [ns for ns in namespaces if ns.lower().startswith(text.lower())]

# ── Command Parsing ──────────────────────────────────────────────────────
def _strip_global(s: str) -> str:
    """Remove leading ^ from a global name."""
    return s.lstrip("^")

def _parse_global_ref(ref: str) -> tuple[str, list]:
    """Parse '"^NS(sub1,sub2)"' or '"NS(sub1,sub2)"' into (ns, [sub1, sub2]).
Supports both '(^NS(...))' and bare '^NS(...)' forms."""
    ref = ref.strip()
    if not ref:
        return "", []

    # Strip outer wrapper: (^NS(...)) or just (^NS(...))
    # If it starts with '(' and the first content is '^', it's a wrapped global ref
    stripped = ref
    if stripped.startswith("("):
        # Find matching close paren by counting depth
        depth = 0
        end = -1
        for i, ch in enumerate(stripped):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end > 0:
            stripped = stripped[1:end]  # Remove outer parens

    # Now parse the inner reference
    if "(" not in stripped:
        return _strip_global(stripped), []

    name, rest = stripped.split("(", 1)
    name = _strip_global(name.strip())
    rest = rest.rstrip(")") if rest.endswith(")") else rest

    # Parse subscripts
    subs = []
    depth = 0
    current = []
    for ch in rest:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            subs.append("".join(current).strip().strip('"').strip("'"))
            current = []
        else:
            current.append(ch)
    if current:
        subs.append("".join(current).strip().strip('"').strip("'"))

    # Try numeric conversion
    parsed = []
    for s in subs:
        try:
            if "." in s:
                parsed.append(float(s))
            else:
                parsed.append(int(s))
        except (ValueError, TypeError):
            parsed.append(s)
    return name, parsed

# ── Command Handlers ────────────────────────────────────────────────────
def _cmd_get(args: list[str], json_out: bool = False) -> str | dict:
    """$G(^NS(subs))"""
    if not args:
        return {"error": "Usage: $G(^NS(subs))"} if json_out else _RED("Usage: $G(^NS(subs))")
    ns, subs = _parse_global_ref("".join(args))
    if not ns:
        return {"error": "Invalid reference"} if json_out else _RED("Invalid reference")
    try:
        result = HANDLERS["pdb_get"]({"ns": ns, "subs": subs})
        val = result.get("value", "")
        if json_out:
            return {"ns": ns, "subs": subs, "value": val}
        if val is None or val == "":
            return _DIM("<undefined>")
        return str(val)
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_order(args: list[str], json_out: bool = False) -> str | dict:
    """$O(^NS(subs),dir)"""
    if not args:
        return {"error": "Usage: $O(^NS(subs),dir)"} if json_out else _RED("Usage: $O(^NS(subs),dir)")
    full = "".join(args)
    parts = full.rsplit(",", 1)
    direction = 1
    ref = full
    if len(parts) == 2 and parts[1].strip() in ("1", "-1"):
        direction = int(parts[1].strip())
        ref = parts[0]
    ns, subs = _parse_global_ref(ref)
    if not ns:
        return {"error": "Invalid reference"} if json_out else _RED("Invalid reference")
    try:
        result = HANDLERS["pdb_order"]({"ns": ns, "subs": subs, "direction": direction})
        val = result.get("value")
        if json_out:
            return {"ns": ns, "subs": subs, "direction": direction, "next": val}
        if val is None:
            return _DIM("<end>")
        return str(val)
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_data(args: list[str], json_out: bool = False) -> str | dict:
    """$D(^NS(subs))"""
    if not args:
        return {"error": "Usage: $D(^NS(subs))"} if json_out else _RED("Usage: $D(^NS(subs))")
    ns, subs = _parse_global_ref("".join(args))
    if not ns:
        return {"error": "Invalid reference"} if json_out else _RED("Invalid reference")
    try:
        result = HANDLERS["pdb_data"]({"ns": ns, "subs": subs})
        code = result.get("code", 0)
        meaning = {0: "does not exist", 1: "has value", 10: "has children", 11: "has value + children"}
        if json_out:
            return {"ns": ns, "subs": subs, "code": code, "meaning": meaning.get(code, "")}
        return f"{code} ({meaning.get(code, '')})"
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_set(args: list[str], json_out: bool = False) -> str | dict:
    """SET ^NS(subs)=value"""
    if not args:
        return {"error": "Usage: SET ^NS(subs)=value"} if json_out else _RED("Usage: SET ^NS(subs)=value")
    full = "".join(args)
    if "=" not in full:
        return {"error": "Missing = in SET"} if json_out else _RED("Missing = in SET")
    ref, value = full.split("=", 1)
    ns, subs = _parse_global_ref(ref.strip())
    if not ns:
        return {"error": "Invalid reference"} if json_out else _RED("Invalid reference")
    value = value.strip().strip('"').strip("'")
    try:
        HANDLERS["pdb_set"]({"ns": ns, "subs": subs, "value": value})
        if json_out:
            return {"ns": ns, "subs": subs, "value": value, "status": "ok"}
        return _GREEN("✓ SET")
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_kill(args: list[str], json_out: bool = False) -> str | dict:
    """KILL ^NS(subs)"""
    if not args:
        return {"error": "Usage: KILL ^NS(subs)"} if json_out else _RED("Usage: KILL ^NS(subs)")
    ns, subs = _parse_global_ref("".join(args))
    if not ns:
        return {"error": "Invalid reference"} if json_out else _RED("Invalid reference")
    try:
        HANDLERS["pdb_kill"]({"ns": ns, "subs": subs})
        if json_out:
            return {"ns": ns, "subs": subs, "status": "ok"}
        return _GREEN("✓ KILL")
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_zwrite(args: list[str], json_out: bool = False) -> str | dict:
    """ZW ^NS(subs) / ZWR ^NS(subs) — Show node + children."""
    if not args:
        namespaces = _list_namespaces()
        if json_out:
            return {"namespaces": namespaces}
        lines = []
        for ns in namespaces:
            lines.append(f"{_BOLD('^'+ns)}")
        return "\n".join(lines)
    ns, subs = _parse_global_ref("".join(args))
    if not ns:
        return {"error": "Invalid reference"} if json_out else _RED("Invalid reference")

    try:
        # Read the value
        get_result = HANDLERS["pdb_get"]({"ns": ns, "subs": subs})
        val = get_result.get("value")

        # Walk children
        children = []
        cursor = ""
        while True:
            order_result = HANDLERS["pdb_order"]({"ns": ns, "subs": subs + [cursor], "direction": 1})
            next_key = order_result.get("value")
            if next_key is None:
                break
            children.append(next_key)
            cursor = next_key

        if json_out:
            n = ".".join(str(s) for s in subs) if subs else "."
            result = {f"^{ns}({n})": val}
            child_data = {}
            for c in children:
                cresult = HANDLERS["pdb_get"]({"ns": ns, "subs": subs + [c]})
                cv = cresult.get("value")
                child_data[str(c)] = cv
            result["children"] = child_data
            return result

        # Formatted output
        ref_str = f"^{ns}({','.join(repr(s) for s in subs)})" if subs else f"^{ns}"
        lines = []
        if val is not None and val != "":
            lines.append(f"{_BOLD(ref_str)} = {_YELLOW(str(val))}")
        else:
            lines.append(f"{_BOLD(ref_str)}")

        for c in children:
            cresult = HANDLERS["pdb_get"]({"ns": ns, "subs": subs + [c]})
            cv = cresult.get("value")
            cref = f"^{ns}({','.join(repr(s) for s in subs)},{repr(c)})" if subs else f"^{ns}({repr(c)})"
            if cv is not None and cv != "":
                lines.append(f"  {_DIM(cref)} = {_YELLOW(str(cv))}")
            else:
                lines.append(f"  {_DIM(cref)}")
        return "\n".join(lines)

    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_percent_gl(args: list[str], json_out: bool = False, pager=None) -> str | dict:
    """D ^%GL [NS] [(range)] — Global Listing"""
    if json_out:
        return _cmd_percent_gl_json(args)
    return _cmd_percent_gl_text(args, pager)

def _parse_subscript_list(text: str) -> list:
    """Parse comma-separated subscript list into a list."""
    if not text:
        return []
    parts = []
    depth = 0
    current = []
    for ch in text:
        if ch == '(':
            depth += 1
            current.append(ch)
        elif ch == ')':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip().strip('"').strip("'"))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip().strip('"').strip("'"))
    result = []
    for p in parts:
        try:
            if '.' in p:
                result.append(float(p))
            else:
                result.append(int(p))
        except (ValueError, TypeError):
            result.append(p)
    return result


def _cmd_percent_gl_text(args: list[str], pager=None) -> str:
    ns_name = None
    base_subs: list = []
    range_start_sub = None
    range_end_sub = None

    full = "".join(args).strip()
    if full:
        if "(" in full:
            name_part, range_part = full.split("(", 1)
            ns_name = name_part.strip().lstrip("^")
            range_part = range_part.rstrip(")")
            if ":" in range_part:
                parts = range_part.split(":", 1)
                range_start_sub = parts[0].strip().strip('"').strip("'") or ""
                range_end_sub = parts[1].strip().strip('"').strip("'") if parts[1] else ""
            else:
                # D ^%GL NS(key1,key2) -> base_subs = [key1, key2], then iterate children
                base_subs = _parse_subscript_list(range_part)
        else:
            ns_name = full.strip().lstrip("^")

    if not ns_name:
        namespaces = _list_namespaces()
        if pager:
            try:
                pager.write(_BOLD(f"PDB Namespaces ({len(namespaces)}):"))
                for ns in namespaces:
                    try:
                        s = HANDLERS["pdb_schema"]({})
                        ns_info = next((n for n in (s.get("namespaces") or []) if n["ns"] == ns), {})
                        cnt = ns_info.get("nodes", "?")
                    except Exception:
                        cnt = "?"
                    pager.write(f"  {_GREEN('^'+ns):30s} {_DIM(f'({cnt} nodes)')}")
                pager.write()
                pager.write(_DIM("Usage: D ^%GL NS  or  D ^%GL NS(sub1,sub2)"))
            except StopIteration:
                pass
            return ""
        else:
            lines = [_BOLD(f"PDB Namespaces ({len(namespaces)}):")]
            for ns in namespaces:
                lines.append(f"  {_GREEN('^'+ns)}")
            return "\n".join(lines)

    page_size = _term_height() - 4
    shown = 0
    cursor = range_start_sub or ""
    try:
        while True:
            subs_for_order = base_subs + ([cursor] if cursor else [""])
            result = HANDLERS["pdb_order"]({"ns": ns_name, "subs": subs_for_order, "direction": 1})
            next_key = result.get("value")
            if next_key is None:
                if shown == 0:
                    empty_msg = f"^{ns_name}"
                    if base_subs:
                        empty_msg += f"({','.join(repr(s) for s in base_subs)})"
                    empty_msg += ": <empty>"
                    if pager:
                        pager.write(_DIM(empty_msg))
                    else:
                        print(_DIM(empty_msg))
                break
            if range_end_sub and str(next_key) > range_end_sub:
                break

            lookup_subs = base_subs + [next_key]
            gresult = HANDLERS["pdb_get"]({"ns": ns_name, "subs": lookup_subs})
            val = gresult.get("value", "")
            label = str(next_key)
            if val and val != "":
                val_str = str(val)[:_term_width() - len(label) - 20]
                line = f"  {_GREEN(label):20s} = {_YELLOW(val_str)}"
            else:
                dresult = HANDLERS["pdb_data"]({"ns": ns_name, "subs": lookup_subs})
                code = dresult.get("code", 0)
                if code in (10, 11):
                    line = f"  {_GREEN(label):20s} {_DIM('(<children>)')}"
                else:
                    line = f"  {_GREEN(label)}"
            shown += 1
            if pager:
                pager.write(line)
            else:
                print(line)
            cursor = next_key

        if pager:
            pager.write(_DIM(f"\n  [{shown} entries]"))
        else:
            print(_DIM(f"\n  [{shown} entries]"))
    except (KeyboardInterrupt, StopIteration):
        pass
    except Exception as e:
        return _RED(f"Error: {e}")
    return ""

def _cmd_percent_gl_json(args: list[str]) -> dict:
    full = "".join(args).strip()
    ns_name = None
    if full:
        if "(" in full:
            ns_name = full.split("(", 1)[0].strip().lstrip("^")
        else:
            ns_name = full.strip().lstrip("^")

    if not ns_name:
        return {"type": "namespaces", "namespaces": _list_namespaces()}

    entries = []
    cursor = ""
    while True:
        result = HANDLERS["pdb_order"]({"ns": ns_name, "subs": [cursor], "direction": 1})
        next_key = result.get("value")
        if next_key is None:
            break
        gresult = HANDLERS["pdb_get"]({"ns": ns_name, "subs": [next_key]})
        entries.append({"key": next_key, "value": gresult.get("value")})
        cursor = next_key

    return {"type": "namespace", "ns": ns_name, "entries": entries}

def _cmd_percent_ss(args: list[str], json_out: bool = False) -> str | dict:
    """D ^%SS — System Status Summary"""
    try:
        schema = HANDLERS["pdb_schema"]({})
        if not isinstance(schema, dict):
            schema = {}

        namespaces = schema.get("namespaces", [])
        db_path = schema.get("database") or _get_db_path()
        db_size = Path(db_path).stat().st_size if Path(db_path).exists() else 0

        if json_out:
            return {
                "database": db_path,
                "size_bytes": db_size,
                "namespaces": len(namespaces),
                "total_nodes": sum(n.get("nodes", 0) for n in namespaces),
            }

        lines = [
            _BOLD("PDB System Status"),
            _DIM("─" * _term_width()),
            f"  Database:  {_CYAN(db_path)}",
            f"  Size:      {_format_bytes(db_size)}",
            f"  Namespaces: {len(namespaces)}",
            f"  Total nodes: {sum(n.get('nodes', 0) for n in namespaces)}",
            "",
            _BOLD("Namespaces:"),
        ]
        for ns in sorted(namespaces, key=lambda n: n.get("nodes", 0), reverse=True):
            nname = ns.get("ns", "?")
            nnodes = ns.get("nodes", 0)
            nvals = ns.get("with_values", 0)
            lines.append(f"  {_GREEN('^'+nname):25s} {_DIM(str(nnodes)+' nodes'):15s} {nnodes - nvals} structural")
        return "\n".join(lines)
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"Error: {e}")

def _cmd_sql(args: list[str], json_out: bool = False) -> str | dict:
    """Run SQL query on _globals table."""
    query = " ".join(args).strip()
    if not query:
        return {"error": "Usage: SQL: SELECT ... FROM _globals WHERE ..."} if json_out else _RED("Usage: SQL: SELECT ... FROM _globals WHERE ...")
    try:
        result = HANDLERS["pdb_query"]({"sql": query})
        if json_out:
            return result
        rows = result.get("rows", [])
        if not rows:
            return _DIM("(no rows)")
        # Format as table
        if rows and isinstance(rows[0], dict):
            headers = list(rows[0].keys())
            col_widths = {h: max(len(h), max((len(str(r.get(h, ""))) for r in rows), default=0)) for h in headers}
            sep = _DIM("─" * (sum(col_widths.values()) + 3 * len(headers)))
            lines = [sep]
            header_line = " | ".join(_BOLD(h.ljust(col_widths[h])) for h in headers)
            lines.append(f"| {header_line} |")
            lines.append(sep)
            for row in rows:
                data_line = " | ".join(str(row.get(h, "")).ljust(col_widths[h]) for h in headers)
                lines.append(f"| {data_line} |")
            lines.append(sep)
            lines.append(_DIM(f"  [{len(rows)} rows]"))
            return "\n".join(lines)
        return "\n".join(str(r) for r in rows)
    except Exception as e:
        return {"error": str(e)} if json_out else _RED(f"SQL Error: {e}")

def _cmd_help(args: list[str], json_out: bool = False) -> str | dict:
    """Show help."""
    cmds = {
        "$G": "$G(^NS(subs))            — Get value at node",
        "$O": "$O(^NS(subs),dir)         — Order traversal (dir=1 forward, -1 backward)",
        "$D": "$D(^NS(subs))             — Data check (returns 0/1/10/11)",
        "SET": "SET ^NS(subs)=value       — Set value",
        "KILL": "KILL ^NS(subs)            — Delete subtree",
        "ZW": "ZW ^NS(subs)               — Write node with children",
        "ZWR": "ZWR ^NS(subs)              — Full ZWRITE output",
        "D ^%GL": "D ^%GL [NS] [(range)] — Global listing",
        "D ^%SS": "D ^%SS                   — System status",
        "SQL:": "SQL: SELECT ...           — Run SQL query",
        "HELP": "HELP [command]            — This help",
        "EXIT": "EXIT / QUIT / Ctrl+D      — Exit shell",
        "--json": "--json flag               — Machine-readable output",
    }

    if json_out:
        return {"commands": cmds}

    topic = " ".join(args).strip().upper() if args else ""
    if topic:
        for cmd, desc in cmds.items():
            if cmd.startswith(topic) or topic in cmd:
                return f"  {_GREEN(cmd):30s} {_DIM(desc.split('—',1)[1].strip())}"
        return _RED(f"No help for '{topic}'")

    lines = [_BOLD("PDB Shell Commands:")]
    lines.append(_DIM("─" * _term_width()))
    for cmd, desc in cmds.items():
        lines.append(f"  {_GREEN(cmd):30s} {_DIM(desc)}")
    lines.append("")
    lines.append(_DIM("Tip: TAB completes namespace names. Enter to paginate long output."))
    return "\n".join(lines)

# ── Dispatch ─────────────────────────────────────────────────────────────
COMMANDS = {
    "$G": _cmd_get, "$GET": _cmd_get,
    "$O": _cmd_order, "$ORDER": _cmd_order,
    "$D": _cmd_data, "$DATA": _cmd_data,
    "SET": _cmd_set,
    "KILL": _cmd_kill,
    "ZW": _cmd_zwrite, "ZWR": _cmd_zwrite, "ZWRITE": _cmd_zwrite,
    "D ^%GL": _cmd_percent_gl,
    "D ^%SS": _cmd_percent_ss,
    "HELP": _cmd_help,
}

def dispatch(line: str, json_out: bool = False, pager=None) -> str | dict | None:
    """Parse and execute a single command line."""
    line = line.strip()
    if not line:
        return None

    # SQL queries
    if line.upper().startswith("SQL:"):
        return _cmd_sql([line[4:].strip()], json_out)
    if line.upper().startswith("SELECT") or line.upper().startswith("WITH"):
        return _cmd_sql([line], json_out)

    # Determine command
    upper = line.upper()

    # Try known commands
    for cmd_prefix, handler in sorted(COMMANDS.items(), key=lambda x: -len(x[0])):
        if upper.startswith(cmd_prefix):
            # Remove the prefix to get args (handle with or without parens)
            rest = line[len(cmd_prefix):].strip()
            # D ^%GL and D ^%SS need specific handling
            if cmd_prefix == "D ^%GL":
                return handler([rest], json_out, pager)
            if cmd_prefix == "D ^%SS":
                return handler([rest], json_out)
            return handler([rest], json_out)

    # Try ZW/ZWR without prefix
    if "(" in line and "^" in line:
        if "=" in line:
            return _cmd_set([line], json_out)
        return _cmd_get([line], json_out)

    # Try direct SET/KILL syntax
    if "=" in line:
        return _cmd_set([line], json_out)

    return _RED(f"Unknown command: {line}")

# ── Entry Point ──────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="PDB Shell — Interactive CLI for PDB")
    parser.add_argument("--json", action="store_true", help="JSON output mode (machine-readable)")
    parser.add_argument("-c", "--command", type=str, help="Single command to execute")
    parser.add_argument("--job", type=str, default="", help="Attach to existing MVM Job by owner")
    args = parser.parse_args()

    json_out = args.json

    # Initialize MVM
    try:
        from mvm import MVM
        _mvm_instance = globals().get('_mvm_instance')
        if _mvm_instance is None:
            _mvm_instance = MVM(pdb_tools)
            globals()['_mvm_instance'] = _mvm_instance
        vm = _mvm_instance
    except Exception as e:
        vm = None

    # Create or attach Job
    job_pid = None
    job_code = []
    if vm:
        if args.job:
            # Attach to existing Job by owner
            existing = vm.get_process_by_owner(args.job)
            if existing:
                job_pid = existing.pid
            else:
                print(_YELLOW(f"Job not found for owner '{args.job}'"))
        else:
            owner = f"pdb_shell_{os.getpid()}"
            job_pid = vm.spawn("", name="pdb_shell", owner=owner)
            vm.tick_all(0)  # register without executing

    # Show database info on start
    db_path = _get_db_path()
    if not args.command:
        job_info = f"  \$J={job_pid}" if job_pid else ""
        print(f"{_BOLD('PDB Shell')}  {_DIM(db_path)}{job_info}")
        print(_DIM("─" * _term_width()))
        print(f"  Type {_GREEN('HELP')} for commands, {_GREEN('EXIT')} to quit")
        print()

    if args.command:
        # One-shot mode
        result = dispatch(args.command, json_out)
        if result is not None:
            if isinstance(result, dict):
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(result)
        return

    # Interactive mode
    use_prompt_toolkit = False
    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            # Only use prompt_toolkit if not in git-bash/MSYS
            term = os.environ.get("TERM", "")
            if "xterm" not in term and "cygwin" not in term:
                use_prompt_toolkit = True
            elif term:
                # In git-bash (xterm), skip prompt_toolkit — use simple input
                pass
            else:
                use_prompt_toolkit = True
    except Exception:
        pass

    if use_prompt_toolkit:
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.completion import Completer, Completion
            from prompt_toolkit.history import FileHistory
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory

            history_path = Path.home() / ".pdb_shell_history"

            class PDBCompleter(Completer):
                def get_completions(self, document, complete_event):
                    text = document.text_before_cursor
                    if "^" in text:
                        after_caret = text.split("^")[-1]
                        for ns in _complete_namespace(after_caret):
                            yield Completion(f"^{ns}", start_position=-len(after_caret) - 1)
                    elif text.upper().startswith("D ^%GL "):
                        after = text[7:].strip()
                        for ns in _complete_namespace(after):
                            yield Completion(ns, start_position=-len(after))
                    elif not text or text.isspace():
                        for cmd in ["$G(", "$O(", "$D(", "SET ", "KILL ", "ZW ", "ZWR ", "D ^%GL", "D ^%SS", "HELP", "EXIT", "SQL:"]:
                            yield Completion(cmd)

            session = PromptSession(
                completer=PDBCompleter(),
                history=FileHistory(str(history_path)),
                auto_suggest=AutoSuggestFromHistory(),
                vi_mode=False,
            )

            while True:
                try:
                    line = session.prompt(_GREEN("PDB> "))
                except (KeyboardInterrupt, EOFError):
                    print()
                    break
                if not line.strip():
                    continue
                if line.upper() in ("EXIT", "QUIT", "Q"):
                    break
                pager = Pager()
                try:
                    result = dispatch(line, json_out, pager)
                    if result is not None:
                        if isinstance(result, dict) and json_out:
                            print(json.dumps(result, indent=2, ensure_ascii=False))
                        elif isinstance(result, str) and result:
                            print(result)
                except StopIteration:
                    pass
                except Exception as e:
                    print(_RED(f"Error: {e}"))
        except Exception:
            use_prompt_toolkit = False

    if not use_prompt_toolkit:
        # Simple input loop (works in all terminals)
        print(_YELLOW("(simple input mode)"))
        while True:
            try:
                line = input(_GREEN("PDB> "))
            except (KeyboardInterrupt, EOFError):
                print()
                break
            if not line.strip():
                continue
            if line.upper() in ("EXIT", "QUIT", "Q"):
                break
            pager = Pager()
            try:
                result = dispatch(line, json_out, pager)
                if result is not None:
                    if isinstance(result, dict) and json_out:
                        print(json.dumps(result, indent=2, ensure_ascii=False))
                    elif isinstance(result, str) and result:
                        print(result)
            except StopIteration:
                pass
            except Exception as e:
                print(_RED(f"Error: {e}"))

def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

if __name__ == "__main__":
    main()
