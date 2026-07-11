"""Añadir multi-file journal con rotación a pdb_journal.py."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_journal import journal_get_control, _get_tools
from pdb_journal import _now, CHANGES_NS

tool_set, tool_get = _get_tools()

def journal_file_create():
    """Crear un nuevo archivo de journal.
    MSM: ^SYS("JOURNAL",index)=file^status^type^size
    Nuestro: ^CHANGES("file",seq)={status,type,size,created}
    """
    # Encontrar el número de archivo más alto + 1
    from pdb_tools import tool_order
    last_key = ""
    while True:
        r = tool_order({"ns": CHANGES_NS, "subs": ["file", last_key], "direction": 1})
        if not r.get("success") or not r.get("value"): break
        last_key = r["value"]
    file_num = (int(last_key) + 1) if last_key else 0

    file_entry = {
        "status": "O",  # Open
        "type": "A",    # Auto-allocation
        "size": 0,
        "ops": 0,
        "created": _now(),
        "closed": None,
    }
    tool_set({"ns": CHANGES_NS, "subs": ["file", file_num], "value": file_entry})
    ctrl["current_file"] = file_num
    tool_set({"ns": CHANGES_NS, "subs": ["control"], "value": ctrl})
    return file_num

def journal_file_get(file_num):
    """Obtener info de un archivo de journal."""
    r = tool_get({"ns": CHANGES_NS, "subs": ["file", file_num]})
    return r.get("value") if r.get("success") else None

def journal_file_close(file_num):
    """Cerrar un archivo (status = F de Full)."""
    f = journal_file_get(file_num)
    if f:
        f["status"] = "F"
        f["closed"] = _now()
        tool_set({"ns": CHANGES_NS, "subs": ["file", file_num], "value": f})

def journal_file_rotate():
    """Cerrar archivo actual y crear nuevo."""
    ctrl = journal_get_control()
    old_file = ctrl.get("current_file")
    if old_file:
        journal_file_close(old_file)
    new_file = journal_file_create()
    return new_file

def journal_file_list():
    """Listar todos los archivos de journal."""
    from pdb_tools import tool_order
    r = []
    key = ""
    while True:
        k = tool_order({"ns": CHANGES_NS, "subs": ["file", key], "direction": 1})
        if not k.get("success") or not k.get("value"): break
        key = k["value"]
        f = journal_file_get(key)
        if f: r.append({"file": key, **f})
    return r

def journal_file_cleanup(keep_last=3):
    """Archivar archivos cerrados viejos (solo mantener keep_last)."""
    files = journal_file_list()
    closed = [f for f in files if f.get("status") == "F"]
    closed.sort(key=lambda x: x["file"])
    old = closed[:-keep_last] if len(closed) > keep_last else []
    from pdb_tools import tool_kill
    for f in old:
        tool_kill({"ns": CHANGES_NS, "subs": ["file", f["file"]]})
    return [f["file"] for f in old]

# CLI
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "create":
        n = journal_file_create()
        print(f"File created: #{n}")
    elif cmd == "rotate":
        n = journal_file_rotate()
        print(f"Rotated to file #{n}")
    elif cmd == "list":
        for f in journal_file_list():
            s = f.get("status")
            emoji = {"O":"🟢","F":"📦","C":"🗄️","E":"⬜"}.get(s,"❓")
            print(f"  {emoji} #{f['file']:2d} {s} | {f.get('ops',0)} ops | {f.get('size',0)}b")
    elif cmd == "cleanup":
        removed = journal_file_cleanup()
        print(f"Cleaned up {len(removed)} old files: {removed}")
