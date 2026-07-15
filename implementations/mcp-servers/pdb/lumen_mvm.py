#!/usr/bin/env python3
"""ctypes bridge for the Tokio MVM scheduler.

Rust owns jobs, gas slices, mpsc mailboxes and timers. SQLite remains the
canonical datastore: every VM global operation calls the normal ``pdb_tools``
API live, and each job snapshot is persisted atomically after a transition.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_CRATE = _REPO / "implementations" / "rust" / "lumen-mvm"
_lib = None
_CALLBACK = ctypes.CFUNCTYPE(
    ctypes.c_ssize_t,
    ctypes.c_void_p,
    ctypes.c_char_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
)


def _lib_path() -> Path:
    override = os.environ.get("LUMEN_MVM_LIB")
    if override:
        return Path(override)
    name = {
        "darwin": "liblumen_mvm.dylib",
        "linux": "liblumen_mvm.so",
    }.get(sys.platform, "lumen_mvm.dll")
    return _CRATE / "target" / "release" / name


def ensure_built(quiet: bool = True) -> bool:
    library = _lib_path()
    sources = [_CRATE / "Cargo.toml", _CRATE / "Cargo.lock"]
    sources.extend((_CRATE / "src").glob("*.rs"))
    mlight = _CRATE.parent / "lumen-m-light"
    sources.extend([mlight / "Cargo.toml", mlight / "Cargo.lock"])
    sources.extend((mlight / "src").glob("*.rs"))
    if library.exists() and (
        os.environ.get("LUMEN_MVM_LIB")
        or all(path.stat().st_mtime <= library.stat().st_mtime for path in sources if path.exists())
    ):
        return True
    if not _CRATE.exists() or not shutil.which("cargo"):
        return False
    result = subprocess.run(
        ["cargo", "build", "--release"],
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
    if not ensure_built():
        raise OSError(f"Tokio MVM dylib unavailable: {_lib_path()}")
    lib = ctypes.CDLL(str(_lib_path()))
    lib.lmvm_new.argtypes = [_CALLBACK, ctypes.c_void_p]
    lib.lmvm_new.restype = ctypes.c_void_p
    lib.lmvm_call_json.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    lib.lmvm_call_json.restype = ctypes.c_void_p
    lib.lmvm_free.argtypes = [ctypes.c_void_p]
    lib.lmvm_string_free.argtypes = [ctypes.c_void_p]
    _lib = lib
    return lib


def available() -> bool:
    try:
        _load()
        return True
    except (OSError, AttributeError):
        return False


class _PdbBridge:
    def __init__(self, pdb_module):
        self.pdb = pdb_module
        self._pid_lock = threading.Lock()
        self._transactions = {}
        self._known_pids = set()
        self._pid_connection = None
        self._pending_callback = None
        self.callback = _CALLBACK(self._dispatch_c)

    def _dispatch_c(self, _context, request_ptr, output_ptr, capacity):
        try:
            raw_request = ctypes.string_at(request_ptr)
            if not output_ptr or not capacity:
                request = json.loads(raw_request.decode("utf-8"))
                response = self.dispatch(request["op"], request.get("args") or {})
                encoded = json.dumps(
                    response, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                self._pending_callback = (raw_request, encoded)
                return len(encoded)
            if self._pending_callback and self._pending_callback[0] == raw_request:
                encoded = self._pending_callback[1]
                self._pending_callback = None
            else:
                request = json.loads(raw_request.decode("utf-8"))
                response = self.dispatch(request["op"], request.get("args") or {})
                encoded = json.dumps(
                    response, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
        except Exception as error:
            encoded = json.dumps(
                {"success": False, "error": str(error)}, separators=(",", ":")
            ).encode("utf-8")
            if not output_ptr or not capacity:
                self._pending_callback = (ctypes.string_at(request_ptr), encoded)
                return len(encoded)
        if len(encoded) + 1 > capacity:
            return -2
        ctypes.memmove(output_ptr, encoded, len(encoded))
        return len(encoded)

    def dispatch(self, operation, args):
        if operation in ("get", "set", "kill", "data", "order", "routine"):
            return self._global_operation(operation, args)
        if operation == "transaction_start":
            return self._transaction_start(int(args["pid"]))
        if operation == "transaction_commit":
            return self._transaction_commit(int(args["pid"]))
        if operation == "transaction_rollback":
            return self._transaction_rollback(int(args["pid"]))
        if operation == "allocate_pid":
            return self._allocate_pid()
        if operation == "persist_job":
            return self._persist_job(args)
        if operation == "forget_pid":
            self._known_pids.discard(str(args["pid"]))
            return {"success": True}
        if operation == "persist_message":
            return self._persist_message(args["snapshot"], args["message"])
        if operation == "load_jobs":
            return self._load_jobs()
        if operation == "persist_cron":
            return self.pdb.tool_set(
                {"ns": "CRON", "subs": [args["name"]], "value": args}
            )
        if operation == "remove_cron":
            return self.pdb.tool_kill({"ns": "CRON", "subs": [args["name"]]})
        if operation == "load_cron":
            return self._load_cron()
        return {"success": False, "error": f"unknown PDB callback: {operation}"}

    def _allocate_pid(self):
        """Allocate $J under BEGIN IMMEDIATE, including legacy Python Jobs."""
        with self._pid_lock:
            if self._pid_connection is None:
                self._pid_connection = self.pdb.pdb_connect(timeout=30)
            connection = self._pid_connection
            try:
                connection.execute("BEGIN IMMEDIATE")
                key = self.pdb.encode_subkey(["next_pid"])
                row = connection.execute(
                    "SELECT value FROM _globals WHERE ns=? AND subkey=?",
                    ["MVM_META", key],
                ).fetchone()
                if row and row["value"] is not None:
                    current = int(float(self.pdb._decode_value(row["value"])))
                else:
                    current = 0
                    rows = connection.execute(
                        "SELECT subkey FROM _globals WHERE ns='PROCESSES'"
                    ).fetchall()
                    for process_row in rows:
                        subs = self.pdb.decode_subkey(process_row["subkey"])
                        if subs:
                            try:
                                current = max(current, int(subs[0]))
                            except (TypeError, ValueError):
                                pass
                pid = current + 1
                connection.execute(
                    "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                    ["MVM_META", key, self.pdb._encode_value(pid)],
                )
                connection.commit()
                return {"success": True, "pid": pid}
            except Exception:
                connection.rollback()
                raise

    def close(self):
        for transaction in self._transactions.values():
            try:
                transaction["connection"].rollback()
                transaction["connection"].close()
            except Exception:
                pass
        self._transactions.clear()
        if self._pid_connection is not None:
            self._pid_connection.close()
            self._pid_connection = None

    def _install_transaction_context(self, pid):
        transaction = self._transactions.get(pid)
        if transaction:
            self.pdb._atomic_ctx.connection = transaction["connection"]
            self.pdb._atomic_ctx.active = True
            self.pdb._atomic_ctx.pending_changes = transaction["pending"]
            self.pdb._atomic_ctx.level = transaction["level"]
        return transaction

    def _clear_transaction_context(self):
        self.pdb._atomic_ctx.connection = None
        self.pdb._atomic_ctx.active = False
        self.pdb._atomic_ctx.pending_changes = []
        self.pdb._atomic_ctx.level = 0

    def _global_operation(self, operation, args):
        pid = int(args.pop("pid", 0))
        self._install_transaction_context(pid)
        try:
            if operation == "get":
                result = self.pdb.tool_get(args)
                result["found"] = result.get("found", result.get("success", False))
                return result
            if operation == "set":
                return self.pdb.tool_set(args)
            if operation == "kill":
                return self.pdb.tool_kill(args)
            if operation == "data":
                return self.pdb.tool_data(args)
            if operation == "order":
                return self.pdb.tool_order(args)
            name = str(args["name"]).upper()
            lines = []
            line = ""
            while True:
                ordered = self.pdb.tool_order(
                    {"ns": "ROUTINE", "subs": [name, line], "direction": 1}
                )
                next_line = ordered.get("value")
                if next_line is None:
                    break
                line = next_line
                if not isinstance(line, (int, float)) and not str(line).isdigit():
                    continue
                value = self.pdb.tool_get(
                    {"ns": "ROUTINE", "subs": [name, line]}
                ).get("value")
                if value is not None:
                    lines.append(str(value))
            return {"success": True, "source": "\n".join(lines) if lines else None}
        finally:
            self._clear_transaction_context()

    def _transaction_start(self, pid):
        transaction = self._transactions.get(pid)
        if transaction:
            level = transaction["level"] + 1
            transaction["connection"].execute(f"SAVEPOINT mvm_{level}")
            transaction["marks"].append(len(transaction["pending"]))
            transaction["level"] = level
            return {"success": True, "level": level}
        connection = self.pdb.pdb_connect(timeout=30)
        connection.execute("BEGIN IMMEDIATE")
        self._transactions[pid] = {
            "connection": connection,
            "pending": [],
            "marks": [],
            "level": 1,
        }
        return {"success": True, "level": 1}

    def _transaction_commit(self, pid):
        transaction = self._transactions.get(pid)
        if not transaction:
            return {"success": False, "error": "TCOMMIT without TSTART"}
        level = transaction["level"]
        connection = transaction["connection"]
        if level > 1:
            connection.execute(f"RELEASE SAVEPOINT mvm_{level}")
            transaction["marks"].pop()
            transaction["level"] = level - 1
            return {"success": True, "level": level - 1}
        try:
            connection.commit()
            self.pdb._publish_atomic_changes(connection, transaction["pending"])
            return {"success": True, "level": 0}
        finally:
            connection.close()
            self._transactions.pop(pid, None)

    def _transaction_rollback(self, pid):
        transaction = self._transactions.get(pid)
        if not transaction:
            return {"success": False, "error": "TROLLBACK without TSTART"}
        level = transaction["level"]
        connection = transaction["connection"]
        if level > 1:
            connection.execute(f"ROLLBACK TO SAVEPOINT mvm_{level}")
            connection.execute(f"RELEASE SAVEPOINT mvm_{level}")
            mark = transaction["marks"].pop()
            del transaction["pending"][mark:]
            transaction["level"] = level - 1
            return {"success": True, "level": level - 1}
        try:
            connection.rollback()
            return {"success": True, "level": 0}
        finally:
            connection.close()
            self._transactions.pop(pid, None)

    def _persist_job(self, snapshot):
        pid = str(snapshot["pid"])
        state = snapshot["vm_state"]
        operations = [
            {"op": "SET", "ns": "STATE", "subs": [pid, "rust_snapshot"], "value": snapshot},
            {"op": "SET", "ns": "STATE", "subs": [pid, "status"], "value": snapshot["status"]},
            {"op": "SET", "ns": "STATE", "subs": [pid, "name"], "value": snapshot["name"]},
            {"op": "SET", "ns": "STATE", "subs": [pid, "pc"], "value": str(state["ip"])},
            {"op": "SET", "ns": "STATE", "subs": [pid, "vars"], "value": json.dumps(state.get("vars", {}), ensure_ascii=False)},
            {"op": "SET", "ns": "STATE", "subs": [pid, "last_run"], "value": str(snapshot["last_run"])},
            {"op": "SET", "ns": "STATE", "subs": [pid, "io"], "value": str(state.get("current_io", 0))},
            {"op": "SET", "ns": "STATE", "subs": [pid, "gas_limit"], "value": str(state.get("gas_limit", 1000))},
            {"op": "SET", "ns": "STATE", "subs": [pid, "gas_budget"], "value": str(state.get("gas_budget", 0))},
            {"op": "SET", "ns": "STATE", "subs": [pid, "gas_total"], "value": str(state.get("gas_used", 0))},
            {"op": "SET", "ns": "STATE", "subs": [pid, "error"], "value": snapshot.get("error", "")},
            {"op": "KILL", "ns": "STATE", "subs": [pid, "mailbox"]},
        ]
        if pid not in self._known_pids:
            operations[:0] = [
                {"op": "SET", "ns": "PROCESSES", "subs": [pid, "code"], "value": snapshot["source"]},
                {"op": "SET", "ns": "PROCESSES", "subs": [pid, "name"], "value": snapshot["name"]},
                {"op": "SET", "ns": "PROCESSES", "subs": [pid, "owner"], "value": snapshot["owner"]},
                {"op": "SET", "ns": "PROCESSES", "subs": [pid, "spawned_at"], "value": snapshot["created_at"]},
            ]
        operations.append(
            {"op": "SET", "ns": "PROCESSES", "subs": [pid, "status"], "value": snapshot["status"]}
        )
        for message in snapshot.get("mailbox", []):
            operations.append(
                {"op": "SET", "ns": "STATE", "subs": [pid, "mailbox", message["id"]], "value": message["content"]}
            )
        if snapshot.get("wake_at") is None:
            operations.append({"op": "KILL", "ns": "SCHEDULE", "subs": [pid]})
        else:
            operations.append(
                {"op": "SET", "ns": "SCHEDULE", "subs": [pid], "value": str(snapshot["wake_at"])}
            )
        result = self.pdb.tool_apply_batch({"operations": operations})
        if result.get("success"):
            self._known_pids.add(pid)
        return result

    def _persist_message(self, snapshot, message):
        pid = str(snapshot["pid"])
        operations = [
            {"op": "SET", "ns": "STATE", "subs": [pid, "status"], "value": snapshot["status"]},
            {"op": "SET", "ns": "PROCESSES", "subs": [pid, "status"], "value": snapshot["status"]},
            {"op": "SET", "ns": "STATE", "subs": [pid, "mailbox", message["id"]], "value": message["content"]},
        ]
        return self.pdb.tool_apply_batch({"operations": operations})

    def _load_jobs(self):
        snapshots = {}
        statuses = {}
        mailboxes = {}
        connection = self.pdb.pdb_connect(readonly=True)
        try:
            rows = connection.execute(
                "SELECT subkey, value FROM _globals WHERE ns='STATE' ORDER BY subkey"
            ).fetchall()
            for row in rows:
                subs = self.pdb.decode_subkey(row["subkey"])
                if len(subs) < 2:
                    continue
                pid = str(subs[0])
                value = self.pdb._decode_value(row["value"])
                if len(subs) == 2 and subs[1] == "rust_snapshot" and isinstance(value, dict):
                    snapshots[pid] = value
                elif len(subs) == 2 and subs[1] == "status":
                    statuses[pid] = value
                elif len(subs) == 3 and subs[1] == "mailbox":
                    mailboxes.setdefault(pid, []).append(
                        {"id": str(subs[2]), "content": value}
                    )
        finally:
            connection.close()

        jobs = []
        for pid in sorted(snapshots, key=lambda value: int(value)):
            snapshot = snapshots[pid]
            snapshot["status"] = statuses.get(pid, snapshot.get("status"))
            snapshot["mailbox"] = mailboxes.get(pid, [])
            jobs.append(snapshot)
            self._known_pids.add(pid)
        return {"success": True, "jobs": jobs}

    def _load_cron(self):
        entries = []
        name = ""
        while True:
            ordered = self.pdb.tool_order(
                {"ns": "CRON", "subs": [name], "direction": 1}
            )
            next_name = ordered.get("value")
            if next_name is None:
                break
            name = str(next_name)
            result = self.pdb.tool_get({"ns": "CRON", "subs": [name]})
            value = result.get("value")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = None
            if isinstance(value, dict) and value.get("type", "mcode") == "mcode":
                entries.append(value)
        return {"success": True, "entries": entries}


class _TokioCron:
    def __init__(self, vm):
        self.vm = vm

    def add(self, name, interval_secs, action, action_type="mcode", enabled=True):
        if action_type != "mcode":
            raise ValueError("Tokio cron supports M code actions; webhook remains on Python MVM")
        return self.vm._call(
            "cron_add", name=name, interval_secs=interval_secs,
            action=action, enabled=enabled,
        )["name"]

    def remove(self, name):
        self.vm._call("cron_remove", name=name)

    def list(self):
        return self.vm._call("cron_list")["entries"]

    def tick(self):
        return 0


class TokioMVM:
    """Drop-in core MVM API backed by the Rust Tokio scheduler."""

    engine = "rust-tokio"

    def __init__(self, pdb_module, max_gas_global=10000):
        self.pdb = pdb_module
        self.max_gas_global = max_gas_global
        self._bridge = _PdbBridge(pdb_module)
        self._lib = _load()
        self._handle = self._lib.lmvm_new(self._bridge.callback, None)
        if not self._handle:
            raise RuntimeError("could not start Tokio MVM")
        self.cron = _TokioCron(self)

    def close(self):
        if getattr(self, "_handle", None):
            self._lib.lmvm_free(self._handle)
            self._handle = None
            self._bridge.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _call(self, operation, **args):
        pointer = self._lib.lmvm_call_json(
            self._handle,
            json.dumps({"op": operation, "args": args}, ensure_ascii=False).encode("utf-8"),
        )
        if not pointer:
            raise RuntimeError("Tokio MVM returned NULL")
        try:
            result = json.loads(ctypes.string_at(pointer).decode("utf-8"))
        finally:
            self._lib.lmvm_string_free(pointer)
        if not result.get("success"):
            raise RuntimeError(result.get("error", f"MVM {operation} failed"))
        return result

    def spawn(self, code, name="", owner="", gas_limit=1000, gas_budget=0):
        effective_budget = int(gas_budget or 0)
        if self.max_gas_global > 0:
            effective_budget = min(
                effective_budget or int(self.max_gas_global),
                int(self.max_gas_global),
            )
        return self._call(
            "spawn", code=code, name=name, owner=owner,
            gas_limit=gas_limit, gas_budget=effective_budget,
        )["pid"]

    def tick(self, max_per_process=100):
        return self._call("tick", max_per_process=max_per_process)["alive"]

    def tick_all(self, max_per_process=100):
        return self._call("tick_all", max_per_process=max_per_process)["alive"]

    def list_processes(self):
        return self._call("list")["processes"]

    def get_process(self, pid):
        for process in self.list_processes():
            if int(process["pid"]) == int(pid):
                return SimpleNamespace(**process)
        return None

    def get_process_by_owner(self, owner):
        for process in self.list_processes():
            if process.get("owner") == owner and process.get("status") != "DEAD":
                return SimpleNamespace(**process)
        return None

    def kill(self, pid):
        return self._call("kill", pid=pid).get("success", False)

    def mailbox_send(self, to_pid, message):
        return self._call("mailbox_send", to_pid=to_pid, message=message)["message_id"]

    def mailbox_read(self, pid):
        return self._call("mailbox_read", pid=pid)["messages"]

    def sleep_process(self, pid, seconds):
        self._call("sleep", pid=pid, seconds=seconds)
        return True

    def wake_process(self, pid, from_schedule=False):
        self._call("wake", pid=pid, from_schedule=from_schedule)
        return True

    def wake(self, pid):
        return self.wake_process(pid)

    def export_state(self, pid):
        return self._call("export", pid=pid)["state"]

    def import_state(self, data):
        return self._call("import", state=data)["pid"]

    def state_save(self, pid):
        state = self.export_state(pid)
        return self.pdb.tool_set(
            {"ns": "STATE", "subs": [str(pid), "snapshot"], "value": state}
        ).get("success", False)

    def state_restore(self, pid):
        result = self.pdb.tool_get(
            {"ns": "STATE", "subs": [str(pid), "snapshot"]}
        )
        state = result.get("value")
        if isinstance(state, str):
            state = json.loads(state)
        return self.import_state(state) if isinstance(state, dict) else -1

    def fork(self, pid, name=""):
        state = self.export_state(pid)
        return self._call("import", state=state, name=name)["pid"]

    def diff_processes(self, pid_a, pid_b):
        a = self.export_state(pid_a)
        b = self.export_state(pid_b)
        a_state, b_state = a["vm_state"], b["vm_state"]
        a_vars, b_vars = a_state.get("vars", {}), b_state.get("vars", {})
        keys = set(a_vars) | set(b_vars)
        return {
            "pid_a": int(pid_a),
            "pid_b": int(pid_b),
            "pc": {"a": a_state["ip"], "b": b_state["ip"], "diff": a_state["ip"] != b_state["ip"]},
            "status": {"a": a["status"], "b": b["status"], "diff": a["status"] != b["status"]},
            "gas_total": {"a": a_state["gas_used"], "b": b_state["gas_used"], "diff": a_state["gas_used"] != b_state["gas_used"]},
            "vars_diff": {key: {"a": a_vars[key], "b": b_vars[key]} for key in sorted(keys) if key in a_vars and key in b_vars and a_vars[key] != b_vars[key]},
            "vars_only_in_a": sorted(set(a_vars) - set(b_vars)),
            "vars_only_in_b": sorted(set(b_vars) - set(a_vars)),
        }

    def promote(self, source_pid, target_pid=None):
        state = self.export_state(source_pid)
        arguments = {"state": state}
        if target_pid is not None:
            arguments["target_pid"] = target_pid
        promoted = self._call("import", **arguments)["pid"]
        self.kill(source_pid)
        return {"status": "promoted", "source_pid": source_pid, "target_pid": promoted}

    def outbox_send(self, pid, payload, priority="normal", msg_type="text"):
        result = self.pdb.tool_incr(
            {"ns": "AGENT_OUTBOX_COUNTER", "subs": [0]}
        )
        message_id = int(result.get("new_value", result.get("value", 1)))
        entry = {
            "msg_id": message_id,
            "pid": int(pid) if str(pid).isdigit() else str(pid),
            "timestamp": time.time(),
            "type": msg_type,
            "payload": payload,
            "priority": priority,
            "status": "pending",
        }
        self.pdb.tool_set(
            {"ns": "AGENT_OUTBOX", "subs": [str(message_id)], "value": json.dumps(entry)}
        )
        return message_id

    def outbox_read(self, limit=10, priority=""):
        messages = []
        message_id = ""
        while True:
            ordered = self.pdb.tool_order(
                {"ns": "AGENT_OUTBOX", "subs": [message_id], "direction": 1}
            )
            if ordered.get("value") is None:
                break
            message_id = str(ordered["value"])
            value = self.pdb.tool_get(
                {"ns": "AGENT_OUTBOX", "subs": [message_id]}
            ).get("value")
            try:
                entry = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                continue
            if not isinstance(entry, dict) or entry.get("status") != "pending":
                continue
            if priority and entry.get("priority") != priority:
                continue
            messages.append(entry)
        priority_order = {"high": 0, "normal": 1, "low": 2}
        messages.sort(
            key=lambda message: (
                priority_order.get(message.get("priority", "normal"), 9),
                message.get("timestamp", 0),
            )
        )
        return messages[:limit]

    def outbox_ack(self, msg_id):
        key = str(msg_id)
        result = self.pdb.tool_get({"ns": "AGENT_OUTBOX", "subs": [key]})
        value = result.get("value")
        try:
            entry = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            return False
        if not isinstance(entry, dict):
            return False
        entry["status"] = "acknowledged"
        entry["acknowledged_at"] = time.time()
        return self.pdb.tool_set(
            {"ns": "AGENT_OUTBOX", "subs": [key], "value": json.dumps(entry)}
        ).get("success", False)

    def outbox_cleanup(self, max_age_secs=86400):
        now = time.time()
        message_id = ""
        while True:
            ordered = self.pdb.tool_order(
                {"ns": "AGENT_OUTBOX", "subs": [message_id], "direction": 1}
            )
            if ordered.get("value") is None:
                break
            message_id = str(ordered["value"])
            value = self.pdb.tool_get(
                {"ns": "AGENT_OUTBOX", "subs": [message_id]}
            ).get("value")
            try:
                entry = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                continue
            if isinstance(entry, dict) and entry.get("status") == "acknowledged" and now - entry.get("timestamp", 0) > max_age_secs:
                self.pdb.tool_kill(
                    {"ns": "AGENT_OUTBOX", "subs": [message_id]}
                )


__all__ = ["TokioMVM", "available", "ensure_built"]
