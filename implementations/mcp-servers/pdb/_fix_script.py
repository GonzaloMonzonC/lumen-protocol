#!/usr/bin/env python3
"""Fix _cmd_percent_gl_text in pdb_shell.py"""
import sys

with open(r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb\pdb_shell.py', 'r') as f:
    lines = f.readlines()

# Find the function boundaries
func_start = None
func_end = None
brace_depth = 0
in_func = False

for i, line in enumerate(lines):
    if 'def _cmd_percent_gl_text(args: list[str], pager=None) -> str:' in line:
        func_start = i
        in_func = True
        continue
    if in_func:
        # Check if we're at the start of a new function at same level
        if line.startswith('def ') and i > func_start:
            func_end = i
            break

if func_end is None:
    func_end = len(lines)

print(f"Function _cmd_percent_gl_text from line {func_start} to {func_end}")

# Build replacement
new_func = '''def _parse_subscript_list(text: str) -> list:
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
            return "\\n".join(lines)

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
            pager.write(_DIM(f"\\n  [{shown} entries]"))
        else:
            print(_DIM(f"\\n  [{shown} entries]"))
    except (KeyboardInterrupt, StopIteration):
        pass
    except Exception as e:
        return _RED(f"Error: {e}")
    return ""
'''

# Replace lines
new_lines = lines[:func_start] + [new_func + '\n'] + lines[func_end:]

with open(r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb\pdb_shell.py', 'w') as f:
    f.writelines(new_lines)

print(f"Replaced from line {func_start} to {func_end}")
print(f"Old: {func_end - func_start} lines, New: {new_func.count(chr(10)) + 1} lines")
