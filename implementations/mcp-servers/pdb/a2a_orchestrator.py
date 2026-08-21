# -*- coding: utf-8 -*-
"""Orquestador A2A — hito 1 de docs/CASOS_USO_AGENTES.md.

Convierte las primitivas ya existentes (PDB, MVM, DDP, macaroons) en ownership,
routing, hibernación y migración seguras entre nodos, sin intervención humana.

Namespaces (convención del doc — la familia S7F3_* se materializa con ns=SPACES
y subkeys MUMPS [space_id, ...]):

  PRESENCE      ^PRESENCE(node_id)          -> {agent_id: {node_id, status, heartbeat_at}}
  SPACES        ^SPACES(space_id,"niches"/"tasks"/"leases",...)  (dual-write del thinking server)
  A2A_ROUTING   ^A2A_ROUTING(request_id)    -> {task_ref, required, status, lease_epoch, granted_to}
  A2A_RUNS      ^A2A_RUNS(run_id)           -> {task_ref, agent_id, node_id, status, epoch, wake_at}
  A2A_MIGRATION ^A2A_MIGRATION(run_id,...)  -> request/lease/snapshot/status/ack
  A2A_EVENTS    ^A2A_EVENTS(seq) + dedupe   -> log lógico + idempotency keys

Fencing: `epoch` es un token monótono por run_id. Un agente solo publica efectos
si su epoch sigue siendo el vigente. Una migración concede epoch mayor; el nodo
antiguo que reaparezca observa epoch obsoleto y se auto-detiene.
"""

import json
import time
import uuid

try:
    from pdb_tools import encode_subkey, decode_subkey
except ImportError:  # ejecución desde otros directorios
    from implementations.mcp_servers.pdb.pdb_tools import encode_subkey, decode_subkey

NS_PRESENCE = "PRESENCE"
NS_SPACES = "SPACES"
NS_ROUTING = "A2A_ROUTING"
NS_RUNS = "A2A_RUNS"
NS_MIGRATION = "A2A_MIGRATION"
NS_EVENTS = "A2A_EVENTS"

RUN_READY = "READY"
RUN_CLAIMED = "CLAIMED"
RUN_WAITING = "WAITING"
RUN_HIBERNATE = "HIBERNATE"
RUN_HALTED = "HALTED"
RUN_DONE = "DONE"

MIG_PREPARE = "PREPARE"
MIG_TRANSFERRED = "TRANSFERRED"
MIG_IMPORTED = "IMPORTED"
MIG_COMMITTED = "COMMITTED"
MIG_ABORTED = "ABORTED"


class A2AOrchestrator:
    """Coordinador A2A sobre una PDB (SQLite con ns/subkey, estilo MUMPS)."""

    def __init__(self, connect, node_id: str):
        self.connect = connect          # callable -> conn (patrón pdb_connect)
        self.node_id = node_id

    # ── helpers ────────────────────────────────────────────────────────────
    def _get(self, ns, subs, default=None):
        conn = self.connect()
        try:
            row = conn.execute(
                "SELECT value FROM _globals WHERE ns=? AND subkey=?",
                (ns, encode_subkey(subs)),
            ).fetchone()
            return json.loads(row[0]) if row else default
        finally:
            conn.close()

    def _set(self, ns, subs, value):
        conn = self.connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                (ns, encode_subkey(subs), json.dumps(value, ensure_ascii=False)),
            )
            conn.commit()
        finally:
            conn.close()

    def _scan(self, ns, prefix_subs):
        """Recorre $ORDER del prefijo: devuelve {subs_tail: value}."""
        conn = self.connect()
        try:
            rows = conn.execute(
                "SELECT subkey, value FROM _globals WHERE ns=?", (ns,)
            ).fetchall()
        finally:
            conn.close()
        out = {}
        for sk, val in rows:
            try:
                subs = decode_subkey(sk)
            except Exception:
                continue
            if len(subs) >= len(prefix_subs) and subs[: len(prefix_subs)] == prefix_subs:
                out[tuple(subs[len(prefix_subs):])] = json.loads(val)
        return out

    # ── presencia (^PRESENCE) ──────────────────────────────────────────────
    def heartbeat(self, ttl_seconds: float = 30.0):
        self._set(NS_PRESENCE, [self.node_id],
                  {"node_id": self.node_id, "status": "up",
                   "heartbeat_at": time.time(), "ttl": ttl_seconds})

    def is_alive(self, node_id: str, now: float | None = None) -> bool:
        p = self._get(NS_PRESENCE, [node_id])
        if not p:
            return False
        now = now if now is not None else time.time()
        return (now - p.get("heartbeat_at", 0)) < p.get("ttl", 30)

    def dead_nodes(self, now: float | None = None) -> list[str]:
        return [n for n in self._scan(NS_PRESENCE, []) if not self.is_alive(n, now)]

    # ── leases con fencing (SPACES [space_id,"leases",task_id]) ────────────
    def acquire_lease(self, space_id: str, task_id: str, agent_id: str,
                      node_id: str, ttl_seconds: float = 60.0) -> dict | None:
        """Concede lease con epoch monótono si no hay propietario vigente."""
        now = time.time()
        cur = self._get(NS_SPACES, [space_id, "leases", task_id])
        if cur and cur.get("expires_at", 0) > now:
            return None  # ya tiene propietario vigente
        epoch = (cur.get("epoch", 0) + 1) if cur else 1
        lease = {"owner_agent": agent_id, "owner_node": node_id, "epoch": epoch,
                 "acquired_at": now, "expires_at": now + ttl_seconds}
        self._set(NS_SPACES, [space_id, "leases", task_id], lease)
        return lease

    def renew_lease(self, space_id: str, task_id: str, agent_id: str, node_id: str,
                    ttl_seconds: float = 60.0) -> dict | None:
        cur = self._get(NS_SPACES, [space_id, "leases", task_id])
        if not cur or cur.get("owner_agent") != agent_id or cur.get("owner_node") != node_id:
            return None
        now = time.time()
        cur["expires_at"] = now + ttl_seconds
        self._set(NS_SPACES, [space_id, "leases", task_id], cur)
        return cur

    def current_epoch(self, space_id: str, task_id: str) -> int:
        cur = self._get(NS_SPACES, [space_id, "leases", task_id])
        return cur.get("epoch", 0) if cur else 0

    # ── sobre A2A e idempotencia (A2A_EVENTS dedupe) ───────────────────────
    def deliver(self, msg: dict, apply_fn) -> dict:
        """Entrega at-least-once con dedupe por idempotency_key."""
        key = msg.get("idempotency_key")
        if key:
            seen = self._get(NS_EVENTS, ["dedupe", key])
            if seen:
                return {"duplicate": True, "result_ref": seen.get("result_ref")}
        result_ref = apply_fn(msg)
        if key:
            seq = self._event_seq()
            self._set(NS_EVENTS, ["dedupe", key], {"event_seq": seq, "result_ref": result_ref})
        return {"duplicate": False, "result_ref": result_ref}

    def _event_seq(self) -> int:
        meta = self._get(NS_EVENTS, ["_meta"], {"seq": 0})
        seq = meta.get("seq", 0) + 1
        self._set(NS_EVENTS, ["_meta"], {"seq": seq})
        return seq

    def log_event(self, etype: str, ref, agent_id: str, epoch: int):
        seq = self._event_seq()
        self._set(NS_EVENTS, [seq], {"type": etype, "ref": ref, "agent_id": agent_id,
                                     "epoch": epoch, "ts": time.time()})

    # ── router (^PRESENCE + A2A_ROUTING) ───────────────────────────────────
    def register_agent(self, agent_id: str, capability: str, node_id: str,
                       ttl_seconds: float = 120.0):
        key = [agent_id, capability]
        cur = self._get(NS_ROUTING, ["caps", *key], {})
        cur.update({"node_id": node_id, "status": "up",
                    "ttl": ttl_seconds, "updated_at": time.time()})
        self._set(NS_ROUTING, ["caps", *key], cur)

    def resolve(self, agent_id: str, capability: str, now: float | None = None) -> str | None:
        """agent_id + capability -> node_id (solo nodos vivos)."""
        caps = self._scan(NS_ROUTING, ["caps"])
        now = now if now is not None else time.time()
        for tail, c in caps.items():
            if len(tail) == 2 and tail[0] == agent_id and tail[1] == capability:
                if self.is_alive(c.get("node_id", ""), now) and \
                   (now - c.get("updated_at", 0)) < c.get("ttl", 120):
                    return c["node_id"]
        return None

    def route(self, request_id: str, task_ref: list, required: str,
              agent_id: str, space_id: str) -> dict:
        """Crea solicitud, resuelve nodo vivo y concede lease con fencing."""
        node = self.resolve(agent_id, required)
        if not node:
            return {"ok": False, "error": "no_capable_node"}
        lease = self.acquire_lease(space_id, task_ref[-1], agent_id, node)
        if not lease:
            return {"ok": False, "error": "lease_busy"}
        self._set(NS_ROUTING, ["requests", request_id],
                  {"task_ref": task_ref, "required": required, "status": "granted",
                   "granted_to": agent_id, "node_id": node, "lease_epoch": lease["epoch"]})
        self.log_event("routing.grant", task_ref, agent_id, lease["epoch"])
        return {"ok": True, "node_id": node, "epoch": lease["epoch"]}

    # ── RUNS: ejecuciones lógicas con wake_at (sobreviven a migración) ─────
    def run_start(self, run_id: str, task_ref: list, agent_id: str, node_id: str,
                  epoch: int, status: str = RUN_READY, wake_at: float | None = None,
                  space_id: str | None = None):
        self._set(NS_RUNS, [run_id], {"task_ref": task_ref, "agent_id": agent_id,
                                      "node_id": node_id, "status": status,
                                      "epoch": epoch, "wake_at": wake_at,
                                      "space_id": space_id or (task_ref[0] if task_ref else "local")})

    def run_hibernate(self, run_id: str, seconds: float, node_id: str):
        r = self._get(NS_RUNS, [run_id])
        if not r or r.get("node_id") != node_id:
            return False
        r["status"] = RUN_HIBERNATE
        r["wake_at"] = time.time() + seconds
        self._set(NS_RUNS, [run_id], r)
        return True

    def run_wake_if_due(self, run_id: str, now: float | None = None) -> bool:
        """^SCHEDULE: despierta al Job si su wake_at ha vencido."""
        r = self._get(NS_RUNS, [run_id])
        if not r:
            return False
        now = now if now is not None else time.time()
        if r.get("status") == RUN_HIBERNATE and r.get("wake_at") and r["wake_at"] <= now:
            r["status"] = RUN_READY
            r["wake_at"] = None
            self._set(NS_RUNS, [run_id], r)
            return True
        return False

    # ── migración segura (A2A_MIGRATION) ───────────────────────────────────
    def migration_request(self, run_id: str, source: str, target: str, reason: str):
        self._set(NS_MIGRATION, [run_id, "request"],
                  {"source": source, "target": target, "reason": reason,
                   "requested_at": time.time()})
        self._set(NS_MIGRATION, [run_id, "status"], MIG_PREPARE)

    def migration_snapshot(self, run_id: str, state_ref: str, code_ref: str,
                           snapshot_hash: str, epoch: int) -> dict:
        """PREPARE: snapshot seleccionado (nunca ^STATE entero)."""
        self._set(NS_MIGRATION, [run_id, "snapshot"],
                  {"state_ref": state_ref, "code_ref": code_ref,
                   "hash": snapshot_hash, "epoch": epoch})
        self._set(NS_MIGRATION, [run_id, "status"], MIG_TRANSFERRED)
        return {"ok": True, "status": MIG_TRANSFERRED}

    def migration_import(self, run_id: str, target_pid: str, target_node: str,
                         epoch: int, snapshot_hash: str, wake_at: float | None) -> dict:
        """IMPORTED: el destino importa con PID nuevo; conserva wake_at si HIBERNATE."""
        r = self._get(NS_RUNS, [run_id])
        if not r:
            return {"ok": False, "error": "unknown_run"}
        # Migración cooperativa: el origen se ha HALTED, el destino toma el
        # ownership con fencing (epoch+1). Cualquier efecto del nodo antiguo
        # queda obsoleto (criterio 6/7).
        space_id = r.get("space_id") or (r.get("task_ref", ["local"])[0] if r.get("task_ref") else "local")
        task_id = r["task_ref"][-1] if r.get("task_ref") else run_id
        now = time.time()
        cur_lease = self._get(NS_SPACES, [space_id, "leases", task_id])
        new_epoch = (cur_lease.get("epoch", 0) if cur_lease else 0) + 1
        lease = {"owner_agent": r.get("agent_id", "?"), "owner_node": target_node,
                 "epoch": new_epoch, "acquired_at": now, "expires_at": now + 60}
        self._set(NS_SPACES, [space_id, "leases", task_id], lease)
        r["node_id"] = target_node
        r["epoch"] = new_epoch
        r["status"] = RUN_READY if r.get("status") != RUN_HIBERNATE else RUN_HIBERNATE
        r["wake_at"] = wake_at if wake_at is not None else r.get("wake_at")
        r["pid"] = target_pid
        self._set(NS_RUNS, [run_id], r)
        self._set(NS_MIGRATION, [run_id, "status"], MIG_IMPORTED)
        return {"ok": True, "epoch": r["epoch"]}

    def migration_ack(self, run_id: str, target_pid: str, target_node: str,
                      epoch: int, snapshot_hash: str):
        self._set(NS_MIGRATION, [run_id, "ack"],
                  {"target_pid": target_pid, "target_node": target_node,
                   "epoch": epoch, "snapshot_hash": snapshot_hash})
        self._set(NS_MIGRATION, [run_id, "status"], MIG_COMMITTED)
        self.log_event("migration.committed", [run_id], "migrator", epoch)

    def stale_node_check(self, run_id: str, node_id: str) -> bool:
        """Criterio 7: un nodo restaurado con epoch antiguo se auto-detiene."""
        r = self._get(NS_RUNS, [run_id])
        if not r:
            return False
        lease = self._get(NS_SPACES, [r.get("space_id") or (r.get("task_ref", ["local"])[0] if r.get("task_ref") else "local"),
                                      "leases",
                                      r["task_ref"][-1] if r.get("task_ref") else run_id])
        current = lease.get("epoch", 0) if lease else 0
        if r.get("node_id") == node_id and r.get("epoch", 0) < current:
            r["status"] = RUN_HALTED
            self._set(NS_RUNS, [run_id], r)
            return True  # auto-detenido por epoch obsoleto
        return False

    # ── macaroon-lite: caveat ns_prefix ────────────────────────────────────
    @staticmethod
    def macaroon_caveat_ok(macaroon: dict, ns: str, op: str) -> bool:
        """Un macaroon solo autoriza el prefijo de Namespace que declara."""
        if not macaroon:
            return False
        if op not in macaroon.get("ops", []):
            return False
        prefix = macaroon.get("ns_prefix", "")
        return ns.startswith(prefix) if prefix else ns in macaroon.get("ns", [])


def new_id() -> str:
    return uuid.uuid4().hex[:12]
