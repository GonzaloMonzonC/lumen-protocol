#!/usr/bin/env python3
"""ctypes binding for the Rust M-Light compiler and resumable VM.

⚠️ CONTRATO DE DEPENDENCIA: este módulo es un FFI wrapper de la DLL Rust.
Los bugs de lógica M se reportan al repo Rust (implementations/rust/),
NO aquí. La "MVM" es Rust; Python es binding + orquestación (ver
docs/SSOT_ARQUITECTURA.md §4 — Layered Architecture).

The Rust VM never opens a database. ``execute_sqlite`` snapshots only the
referenced namespaces and writes the final diff through ``pdb_tools`` so the
canonical SQLite engine keeps owning encoding, triggers, indices and journal.
Legacy note: `pdb_tools` defaults to the **Rust evaluator** (`MLIGHT_ENGINE` default `"rust"` desde 15-08-2026, tras verificar paridad de tests — 6.4× más rápido). El evaluador Python (`m_light.py`) queda como fallback/legacy con `MLIGHT_ENGINE=python`.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_CRATE = _REPO / "implementations" / "rust" / "lumen-m-light"
_NS_RE = re.compile(r"\^([A-Za-z%][A-Za-z0-9%]*)")
_lib = None


def _lib_path() -> Path:
    override = os.environ.get("LUMEN_MLIGHT_LIB")
    if override:
        return Path(override)
    name = {
        "darwin": "liblumen_mlight.dylib",
        "linux": "liblumen_mlight.so",
    }.get(sys.platform, "lumen_mlight.dll")
    return _CRATE / "target" / "release" / name


def ensure_built(quiet: bool = True) -> bool:
    """Build the release cdylib when it is absent or older than its sources."""
    library = _lib_path()
    external = bool(os.environ.get("LUMEN_MLIGHT_LIB"))
    sources = [_CRATE / "Cargo.toml", _CRATE / "Cargo.lock"]
    sources.extend((_CRATE / "src").glob("*.rs"))
    if library.exists() and (
        external
        or all(path.stat().st_mtime <= library.stat().st_mtime for path in sources if path.exists())
    ):
        return True
    if not _CRATE.exists() or not shutil.which("cargo"):
        return False
    result = subprocess.run(
        ["cargo", "build", "--release", "--features", "minreq"],
        cwd=_CRATE,
        capture_output=quiet,
        text=True,
        check=False,
    )
    return result.returncode == 0 and library.exists()


def _load():
    global _lib
    if _lib is not None:
        return _lib
    library = _lib_path()
    if not library.exists() and not ensure_built():
        raise OSError(f"M-Light Rust dylib unavailable: {library}")
    lib = ctypes.CDLL(str(library))
    lib.lm_compile_json.argtypes = [ctypes.c_char_p]
    lib.lm_compile_json.restype = ctypes.c_void_p
    lib.lm_execute_json.argtypes = [ctypes.c_char_p]
    lib.lm_execute_json.restype = ctypes.c_void_p
    lib.lm_string_free.argtypes = [ctypes.c_void_p]
    lib.lm_string_free.restype = None
    _lib = lib
    return lib


def available() -> bool:
    try:
        _load()
        return True
    except (OSError, AttributeError):
        return False


def _call(symbol: str, payload: str):
    lib = _load()
    pointer = getattr(lib, symbol)(payload.encode("utf-8"))
    if not pointer:
        raise RuntimeError(f"{symbol} returned NULL")
    try:
        return json.loads(ctypes.string_at(pointer).decode("utf-8"))
    finally:
        lib.lm_string_free(pointer)


def compile_source(source: str) -> dict:
    result = _call("lm_compile_json", source)
    if "error" in result:
        raise ValueError(result["error"])
    return result


def execute(
    source: str | None = None,
    *,
    program: dict | None = None,
    state: dict | None = None,
    variables: dict | None = None,
    job_id: int = 0,
    globals_: list[dict] | None = None,
    routines: dict | None = None,
    input_: list[str] | None = None,
    gas_limit: int | None = None,
    gas_level: str | None = None,
    gas_budget: int = 0,
    slice_gas: int | None = None,
    llm_api_keys: dict[str, str] | None = None,
    sqlite_path: str | None = None,
    sandbox: bool = False,
) -> dict:
    # Gas por NIVELES (ver gas.py). Dos preguntas separadas:
    #   turno  = cuanto puede costar UN turno (el slice)  -> gas_limit
    #   budget = cuanto la operacion ENTERA (0 = sin tope) -> gas_budget
    # Asi un import de un millon de registros corre en muchos turnos sin agotar
    # nada. Antes gas_limit era 1000 y a las ~250 escrituras cortaba, devolviendo
    # execution="completed" con el estado a medias.
    try:
        from gas import resolver as _gas_resolver
        _g = _gas_resolver(gas_level, gas_limit, gas_budget if gas_budget else None)
        _gas_turno, _gas_turnos = _g["turno"], _g["turnos"]
        _gas_budget, _gas_nivel = _g["budget"], _g["nivel"]
    except Exception:
        _gas_turno = gas_limit if gas_limit is not None else 10_000_000
        _gas_turnos, _gas_budget, _gas_nivel = None, gas_budget, "normal"
    if llm_api_keys is None:
        import os as _os
        llm_api_keys = {}
        for var, provider in [("OPENROUTER_API_KEY", "openrouter"), ("DEEPSEEK_API_KEY", "deepseek")]:
            val = _os.environ.get(var)
            if val:
                llm_api_keys[provider] = val
    request = {
        "source": source,
        "program": program,
        "state": state,
        "vars": variables or {},
        "job_id": job_id,
        "globals": globals_ or [],
        "routines": routines or {},
        "input": input_ or [],
        "gas_limit": _gas_turno,
        "gas_budget": _gas_budget,
        "llm_api_keys": llm_api_keys,
        "sqlite_path": sqlite_path,
        "sandbox": sandbox,
    }
    if slice_gas is not None:
        request["slice_gas"] = slice_gas
    response = _call("lm_execute_json", json.dumps(request, ensure_ascii=False))
    # Auto-reanudacion: el motor devuelve `yielded` al agotar el TURNO (o al
    # esperar un device). Se reanuda hasta terminar o hasta agotar los turnos
    # del nivel. Esto es lo que permite operaciones de millones de registros:
    # el coste no tiene que caber en un solo numero, se paga en turnos.
    #
    # El sleep de 0.1s solo tiene sentido cuando se espera un device (LLM); si
    # es por gas, reanudar de inmediato es correcto y 100x mas rapido.
    max_loops = _gas_turnos if _gas_turnos is not None else 10_000
    loop_count = 0
    import time as _time
    while str(response.get("execution") or "") == "yielded" and loop_count < max_loops:
        loop_count += 1
        st = response.get("state") or {}
        # ¿espera un device o es corte de gas? last_open_device != 0 -> device
        if st.get("last_open_device"):
            _time.sleep(0.1)  # dar tiempo al hilo del LLM
        request["state"] = st
        request["gas_limit"] = _gas_turno
        if _gas_budget:
            request["gas_budget"] = _gas_budget
        response = _call("lm_execute_json", json.dumps(request, ensure_ascii=False))
        # tope total acumulado: si se paso, parar
        if _gas_budget and (response.get("state") or {}).get("gas_used", 0) >= _gas_budget:
            break
    response["_turnos_usados"] = loop_count
    if not response.get("ok") and response.get("execution") != "error":
        raise RuntimeError(response.get("error", "Rust M-Light execution failed"))

    # Nunca devolver "completed" con el estado a medias: el motor senala el
    # agotamiento de gas con `yielded`, no con error. Si el consumidor no lo
    # reanuda, el resultado se reporta como out_of_gas + globals_complete=False.
    try:
        from gas import clasificar_resultado as _gas_clasificar
        response = _gas_clasificar(response)
        response["gas_level"] = _gas_nivel
        response["gas_limit"] = _gas_turno
        response["gas_turnos_usados"] = loop_count
    except Exception:
        pass
    return response


def referenced_namespaces(source: str) -> list[str]:
    """Return source namespaces in stable first-use order."""
    return list(dict.fromkeys(_NS_RE.findall(source)))


def _decode_db_value(value):
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def snapshot_sqlite(namespaces: list[str]) -> list[dict]:
    """Read complete namespaces through the public SQLite connection contract."""
    if not namespaces:
        return []
    sys.path.insert(0, str(_HERE))
    from pdb_tools import decode_subkey, pdb_connect, tool_data, tool_get

    # Ensure a brand-new PDB has its schema before opening the readonly view.
    tool_data({"ns": namespaces[0], "subs": []})
    for namespace in namespaces:
        mapped = tool_get({"ns": "MAP_CFG", "subs": [namespace]})
        partitioned = tool_get({"ns": "PART_CFG", "subs": [namespace]})
        if mapped.get("found", True) or partitioned.get("found", True):
            raise ValueError(
                f"namespace {namespace} is mapped/partitioned; Rust snapshot host supports the canonical SQLite file only"
            )

    connection = pdb_connect(readonly=True)
    try:
        entries = []
        for namespace in namespaces:
            rows = connection.execute(
                "SELECT subkey, value FROM _globals WHERE ns=? ORDER BY subkey",
                [namespace],
            ).fetchall()
            entries.extend(
                {
                    "ns": namespace,
                    "subs": decode_subkey(row["subkey"]),
                    "value": _decode_db_value(row["value"]),
                }
                for row in rows
                if row["value"] is not None
            )
        return entries
    finally:
        connection.close()


def _entry_key(entry: dict) -> str:
    return json.dumps([entry["ns"], entry.get("subs", [])], ensure_ascii=False, separators=(",", ":"))


def persist_sqlite_diff(before: list[dict], after: list[dict]) -> None:
    """Apply a VM snapshot diff through PDB tools (triggers/index/journal intact)."""
    sys.path.insert(0, str(_HERE))
    from pdb_tools import tool_apply_batch

    old = {_entry_key(entry): entry for entry in before}
    new = {_entry_key(entry): entry for entry in after}
    removed = sorted(
        (old[key] for key in old.keys() - new.keys()),
        key=lambda entry: len(entry.get("subs", [])),
    )
    roots = []
    for entry in removed:
        subs = entry.get("subs", [])
        if any(
            root["ns"] == entry["ns"]
            and subs[: len(root.get("subs", []))] == root.get("subs", [])
            for root in roots
        ):
            continue
        roots.append(entry)
    operations = [
        {"op": "KILL", "ns": entry["ns"], "subs": entry.get("subs", [])}
        for entry in roots
    ]
    for key, entry in new.items():
        if key in old and old[key].get("value") == entry.get("value"):
            continue
        operations.append(
            {
                "op": "SET",
                "ns": entry["ns"],
                "subs": entry.get("subs", []),
                "value": entry.get("value"),
            }
        )
    touched = {
        _entry_key({"ns": operation["ns"], "subs": operation.get("subs", [])})
        for operation in operations
    }
    preconditions = []
    for key in touched:
        entry = old.get(key)
        if entry is None:
            ns, subs = json.loads(key)
            preconditions.append({"ns": ns, "subs": subs, "found": False})
        else:
            preconditions.append(
                {
                    "ns": entry["ns"],
                    "subs": entry.get("subs", []),
                    "found": True,
                    "value": entry.get("value"),
                }
            )
    result = tool_apply_batch(
        {"operations": operations, "preconditions": preconditions}
    )
    if not result.get("success"):
        raise RuntimeError(result.get("error", "atomic PDB batch failed"))


def execute_sqlite(
    source: str,
    *,
    persist: bool = True,
    namespaces: list[str] | None = None,
    sqlite_path: str | None = None,
    **kwargs,
) -> dict:
    """Execute Rust M-Light against the canonical SQLite PDB.

    Two modes:
    1. Default (snapshot): snapshots namespaces from SQLite → Rust MVM → persist diff
    2. Direct (sqlite_path): passes DB path to Rust MVM which opens SQLite directly.
       $O, $D, $S, $K work natively against SQLite. No snapshot/persist overhead.
    """
    if sqlite_path:
        # Filter kwargs: only pass what execute() understands
        exec_kwargs = {k: v for k, v in kwargs.items()
                       if k in ('variables', 'gas_limit', 'gas_budget', 'slice_gas',
                                'routines', 'input_', 'llm_api_keys')}
        return execute(source, sqlite_path=sqlite_path, **exec_kwargs)
    selected_namespaces = namespaces or referenced_namespaces(source)
    if "@" in source and not selected_namespaces:
        raise ValueError(
            "dynamic indirection requires namespaces=[...] at the SQLite snapshot boundary"
        )
    before = snapshot_sqlite(selected_namespaces)
    response = execute(source, globals_=before, **kwargs)
    if persist and response.get("execution") in {"completed", "halted"}:
        persist_sqlite_diff(before, response.get("globals", []))
    return response


def save_state(job_id, state: dict) -> dict:
    """Persist a serializable gas/VM state in ^STATE(job,"m_light_rust")."""
    sys.path.insert(0, str(_HERE))
    from pdb_tools import tool_set

    return tool_set(
        {"ns": "STATE", "subs": [job_id, "m_light_rust"], "value": state}
    )


def load_state(job_id) -> dict | None:
    """Load a state previously stored by :func:`save_state`."""
    sys.path.insert(0, str(_HERE))
    from pdb_tools import tool_get

    result = tool_get({"ns": "STATE", "subs": [job_id, "m_light_rust"]})
    return result.get("value") if result.get("success") and result.get("found", True) else None


__all__ = [
    "available",
    "compile_source",
    "ensure_built",
    "execute",
    "execute_sqlite",
    "load_state",
    "persist_sqlite_diff",
    "referenced_namespaces",
    "save_state",
    "snapshot_sqlite",
]
