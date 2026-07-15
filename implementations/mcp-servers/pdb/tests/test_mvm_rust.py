"""Fase 6 integration tests: Tokio scheduler against the real SQLite PDB."""

import os
import subprocess
import sys
from pathlib import Path


PDB_DIR = Path(__file__).resolve().parents[1]


def test_tokio_mvm_live_storage_mailbox_timer_and_restore(tmp_path):
    script = r'''
import time
import os
import pdb_tools
from mvm import MVM

assert MVM.__module__ == "lumen_mvm", MVM
assert pdb_tools.tool_set({"ns":"PROCESSES","subs":["41","code"],"value":"S legacy=1"})["success"]
vm = MVM(pdb_tools)

# Live SQLite host and gas yield: the second SET is not visible after tick one.
pid = vm.spawn('S ^LIVE("x")=1\nS ^LIVE("y")=$G(^LIVE("x"))+1', name="live", gas_limit=1)
assert pid == 42  # allocator scans Python/legacy Jobs before creating Rust $J
vm.tick_all(1)
assert pdb_tools.tool_get({"ns":"LIVE","subs":["x"]})["value"] == 1.0
assert pdb_tools.tool_get({"ns":"LIVE","subs":["y"]}).get("found") is False
vm.tick_all(1)
assert pdb_tools.tool_get({"ns":"LIVE","subs":["y"]})["value"] == 2.0

# The live callback honors namespace mapping and real TSTART/TCOMMIT semantics.
mapped = os.path.join(os.path.dirname(os.environ["PDB_PATH"]), "mapped.db")
assert pdb_tools.tool_map_set({"ns":"MAPPED","db_path":mapped})["success"]
mapped_job = vm.spawn('S ^MAPPED("live")=1', name="mapped")
vm.tick_all(1)
assert pdb_tools.tool_get({"ns":"MAPPED","subs":["live"]})["value"] == 1.0
tx_job = vm.spawn('TSTART\nS ^TX("a")=1\nS ^TX("b")=2\nTCOMMIT', name="tx")
vm.tick_all(1)
assert vm.get_process(tx_job).status == "DEAD"  # transaction never yields mid-flight
assert pdb_tools.tool_get({"ns":"TX","subs":["b"]})["value"] == 2.0
nested = vm.spawn('TSTART\nS ^TX("outer")=1\nTSTART\nS ^TX("discard")=1\nTROLLBACK\nTCOMMIT', name="nested-tx")
vm.tick_all(1)
assert pdb_tools.tool_get({"ns":"TX","subs":["outer"]})["value"] == 1.0
assert pdb_tools.tool_get({"ns":"TX","subs":["discard"]}).get("found") is False

# External routines are loaded live from the canonical ^ROUTINE tree.
pdb_tools.tool_set({"ns":"ROUTINE","subs":["PHASE6",1],"value":'S ^ROUTINEOUT("ok")=$1'})
routine_job = vm.spawn('D ^PHASE6(7)', name="routine")
vm.tick_all(20)
assert pdb_tools.tool_get({"ns":"ROUTINEOUT","subs":["ok"]})["value"] == 7.0

budgeted = vm.spawn('S a=1\nS b=2', name="budget", gas_budget=1)
vm.tick_all(20)
assert vm.get_process(budgeted).status == "DEAD"
assert "gas budget exhausted" in vm.get_process(budgeted).error

# READ without a message yields WAITING; mpsc delivery wakes and resumes it.
reader = vm.spawn('R msg\nS ^MAIL("got")=msg', name="reader")
vm.tick_all(20)
assert vm.get_process(reader).status == "WAITING"
assert pdb_tools.tool_get({"ns":"MAIL","subs":["got"]}).get("found") is False
vm.mailbox_send(reader, {"hello":"tokio"})
assert vm.get_process(reader).status == "READY"
vm.tick_all(20)
assert pdb_tools.tool_get({"ns":"MAIL","subs":["got"]})["value"] == '{"hello":"tokio"}'

# HIBERNATE wakes through tokio::time without scheduler polling.
sleeper = vm.spawn('S ^WAKE("done")=1', name="sleeper")
vm.sleep_process(sleeper, 0.05)
assert vm.get_process(sleeper).status == "HIBERNATE"
time.sleep(0.09)
assert vm.get_process(sleeper).status == "READY"

# Snapshot is durable and loaded into a new scheduler instance.
restored_pid = vm.spawn('S a=1\nS ^RESTORE("ok")=a', name="restore", gas_limit=1)
vm.tick_all(1)
assert vm.get_process(restored_pid).status == "READY"
assert vm.state_save(restored_pid)
forked_pid = vm.fork(restored_pid, name="forked")
assert vm.diff_processes(restored_pid, forked_pid)["pc"]["diff"] is False
saved_copy = vm.state_restore(restored_pid)
assert vm.get_process(saved_copy).status == "READY"

outbox_id = vm.outbox_send(restored_pid, {"phase": 6}, priority="high", msg_type="json")
assert vm.outbox_read(priority="high")[0]["msg_id"] == outbox_id
assert vm.outbox_ack(outbox_id)
vm.close()
vm2 = MVM(pdb_tools)
assert vm2.get_process(restored_pid).status == "READY"
vm2.tick_all(1)
assert pdb_tools.tool_get({"ns":"RESTORE","subs":["ok"]})["value"] == 1.0

# A persisted HIBERNATE timer is re-armed with its remaining duration.
restart_sleeper = vm2.spawn('S ^WAKE("restart")=1', name="restart-sleeper")
vm2.sleep_process(restart_sleeper, 0.10)
vm2.close()
vm2 = MVM(pdb_tools)
assert vm2.get_process(restart_sleeper).status == "HIBERNATE"
time.sleep(0.14)
assert vm2.get_process(restart_sleeper).status == "READY"

# Cron is driven by a Tokio timer and persists in ^CRON.
vm2.cron.add("phase6", 0.04, 'S ^CRONRESULT("fired")=1')
time.sleep(0.15)
cron_jobs = [p for p in vm2.list_processes() if p["name"] == "cron:phase6"]
assert cron_jobs
vm2.tick_all(20)
assert pdb_tools.tool_get({"ns":"CRONRESULT","subs":["fired"]})["value"] == 1.0
vm2.cron.remove("phase6")
vm2.close()
'''
    environment = os.environ.copy()
    environment.update(
        {
            "MVM_ENGINE": "rust",
            "PDB_PATH": str(tmp_path / "mvm-rust.db"),
            "PYTHONPATH": str(PDB_DIR),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
