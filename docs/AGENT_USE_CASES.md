# A2A use cases: agents that share Namespaces across nodes

> Status: architecture guide, 2026-07-15. Complements the M-Agent v0.3 spec.
> The actors in this document are agents, MVM Jobs and nodes. A person is not
> part of the execution flow.

## 1. What problem it solves

LUMEN should not model these cases as an application that presents data to a
person. The product is a network of agents that:

- share facts and work through PDB Namespaces replicated by DDP;
- notify each other through mailboxes, sending references instead of duplicating data;
- persist their execution in the MVM;
- can remain in `WAITING` or `HIBERNATE` without consuming CPU;
- can move their state to another node and continue from the same instruction;
- delegate access with macaroons limited by Namespace and operation.

There are three distinct planes:

| Plane | Primitive | What it carries |
|-------|-----------|-----------------|
| Data | PDB + DDP | Shared facts, tasks, results, artifacts and events |
| Control | MVM mailbox | Small notices that point to a value in the Namespace |
| Execution | `^STATE`, `^PROCESSES`, `^SCHEDULE` | Durable state, gas, mailbox and the Job's next wake-up |

The Namespace is the source of truth. The mailbox only accelerates the
reaction. If a notice is lost or arrives duplicated, the agent rebuilds its
state by reading the Namespace and the DDP journal.

## 2. Common A2A contract

### 2.1 Identities

- `agent_id`: stable logical identity, for example `planner-7`.
- `node_id`: machine that runs the agent, for example `edge-bcn-02`.
- `pid`: local instance of an MVM Job. It may change when the state is imported
  on another node, so it is never used as the agent's global identity.
- `run_id`: logical execution that survives retries and migrations.

The router resolves `agent_id → node_id → pid` by querying `^PRESENCE`. The
sender never persists the remote PID as a durable address: after a migration it
resolves the logical identity again before delivering the message.

### 2.2 Message envelope

An A2A message carries control information, not the complete result:

```json
{
  "v": 1,
  "id": "msg-01JZ...",
  "type": "task.ready",
  "from": "planner-7",
  "to": "capability:research",
  "space_id": "space-7f3",
  "namespace": "S7F3_TASKS",
  "ref": ["niche-lumen", "T-18"],
  "correlation_id": "space-7f3",
  "causation_id": "evt-1042",
  "idempotency_key": "space-7f3:T-18:ready:3",
  "created_at": "2026-07-15T12:00:00Z",
  "ttl_seconds": 300
}
```

The receiver deduplicates by `idempotency_key` and then reads the current value
of `^S7F3_TASKS("niche-lumen","T-18")`. It does not blindly execute the content
of the message.

### 2.3 Ownership and exclusion across nodes

Each executable unit holds a lease:

```text
^S7F3_TASKS(niche,task,"lease") = {
  owner_agent, owner_node, epoch, acquired_at, expires_at
}
```

`epoch` is a monotonic fencing token. An agent publishes effects only if the
`epoch` of its lease is still the current one. Renewing an expired lease
increments the token; any result from a previous owner becomes stale.

`$LOCK` protects concurrency over the PDB shared by a process or by a node, but
it is not by itself a distributed lock across DDP replicas. Multi-node cases
MUST use one of these policies:

1. an authoritative node grants leases and fencing tokens; or
2. a coordinator with linearizable compare-and-set grants ownership.

DDP's timestamp-based resolution is used to replicate data, not to safely pick
between two concurrent owners.

### 2.4 Delivery, ordering and idempotency

- DDP retries unconfirmed changes: the application assumes **at-least-once**
  delivery.
- `^CHANGES("journal",seq)` orders changes within a node's journal; it is not a
  global clock across nodes.
- Every external effect includes `run_id`, `idempotency_key` and `lease.epoch`.
- A consumer advances its cursor only after persisting the effect or its ack.
- A replicated `KILL` is treated as an idempotent operation.

### 2.5 Authorization

Each agent receives the minimum capability it needs:

| Agent role | Read | Write |
|------------|------|-------|
| Planner | Entire Space | plan, dependencies and new tasks |
| Worker | assigned task + dependencies | lease, progress and its own result |
| Reviewer | specification + result | verdict and review evidence |
| Migrator | snapshot of one `run_id` | migration protocol and ack |
| Observer | events and metrics | none |

Macaroons must include `ns_prefix`, `op` and `expiry`. An agent can attenuate a
capability when delegating it, but never expand it.

### 2.6 Space: the logical unit of sharing

A **Namespace** is a physical PDB tree. A **Space** is a logical unit that
groups several Namespaces which must be discovered, authorized and synchronized
as a set.

A Space can contain one or several niches. The kanban is only a projection of
its niches and tasks; it does not by itself represent the whole Space. Context,
evidence, artifacts, routing and executions can live in different trees while
still belonging to the same Space.

Each Space receives a stable physical prefix derived from its `space_id`. For
example, `space-7f3` uses `S7F3_`:

```text
^S7F3_META         manifest, version, members and policy
^S7F3_NICHES       definition of the shared niches
^S7F3_TASKS        tasks, columns, dependencies and leases
^S7F3_CONTEXT      working memory referenced by the tasks
^S7F3_ARTIFACTS    results and objects produced
^S7F3_EVENTS       logical log and idempotency keys of the Space
^S7F3_WORKFLOW     DAG of distributed steps (optional)
^S7F3_KNOWLEDGE    shared facts and relations (optional)
^S7F3_EVIDENCE     provenance and evidence (optional)
^S7F3_ROUTING      execution requests and grants (optional)
^S7F3_CAPABILITIES offers from agents admitted to the Space (optional)
^S7F3_RUNS         logical processes and ownership (optional)
^S7F3_MIGRATION    selected snapshots and migration ack (optional)
^S7F3_INCIDENTS    autonomous incident coordination (optional)
```

This family lets the existing caveat `ns_prefix=S7F3_` authorize every tree in
the Space and none in another Space. Storing `space_id` as the first subscript
inside global Namespaces would also be possible, but the current macaroon only
restricts by Namespace name, not by subtree; it would need a new
`sub_prefix` caveat.

The manifest describes the bundle:

```text
^S7F3_META("manifest") = {
  space_id: "space-7f3",
  schema_version: 1,
  generation: 12,
  required: ["S7F3_NICHES","S7F3_TASKS","S7F3_EVENTS"],
  optional: ["S7F3_CONTEXT","S7F3_ARTIFACTS",
             "S7F3_WORKFLOW","S7F3_KNOWLEDGE","S7F3_EVIDENCE",
             "S7F3_ROUTING","S7F3_CAPABILITIES","S7F3_RUNS",
             "S7F3_MIGRATION","S7F3_INCIDENTS"],
  owner_node: "node-a",
  authority_epoch: 8
}
^S7F3_META("member",agent_id) = {role, node_id, status, joined_at}
^S7F3_META("barrier",generation) = {journal_seq, root_hash, created_at}
^S7F3_META("cursor",node_id,namespace) = last_applied_seq
```

A node does not expose the Space until it has received all `required`
Namespaces of the same `generation`. It can receive the optional ones later.
This way a task never appears active before the niche or the policy that
defines it.

## 3. Summary of cases

| ID | Case | Main Namespaces | MVM state |
|----|------|-----------------|-----------|
| A2A-01 | Shared cognitive Space | `^S7F3_*` family | READY, WAITING, HIBERNATE |
| A2A-02 | Pipeline of specialists | `^S7F3_WORKFLOW`, `^S7F3_CONTEXT` | WAITING |
| A2A-03 | Shared context and evidence | `^S7F3_KNOWLEDGE`, `^S7F3_EVIDENCE` | READY |
| A2A-04 | Durable wait for a dependency | `^S7F3_*` family, local `^SCHEDULE` | HIBERNATE |
| A2A-05 | Moving an agent between nodes | `^S7F3_MIGRATION`, local `^STATE` | HALTED → READY |
| A2A-06 | Failover of a failed agent | `^PRESENCE`, `^S7F3_MIGRATION` | HIBERNATE/DEAD |
| A2A-07 | Capability discovery and routing | `^S7F3_CAPABILITIES`, `^S7F3_ROUTING` | WAITING |
| A2A-08 | Autonomous incident response | `^S7F3_INCIDENTS`, `^S7F3_EVIDENCE` | READY/BLOCKED |

The domain Namespaces in this table are application conventions; they do not
encroach on the reserved MVM Namespaces described in `spec-m-agent.md`. Cases
A2A-02 to A2A-08 can be mounted as additional capabilities inside the Space
described in A2A-01.

## 4. A2A-01 — Shared cognitive Space between two nodes

### Goal

`node-a` and `node-b`, both with PDB and MVM, share a Space that contains
several LUMEN niches. The agents on both nodes see the same kanban, tasks,
context and artifacts. They can then route work and move processes between
nodes without turning the Space into a single monolithic database.

The shared object is `space-7f3`, not `^KANBAN` and not the whole PDB.

### Space composition

```text
^S7F3_NICHES(niche_id)                         = {name, columns, policy}
^S7F3_TASKS(niche_id,task_id,"spec")          = {kind, input_refs, acceptance}
^S7F3_TASKS(niche_id,task_id,"status")        = READY|CLAIMED|WAITING|REVIEW|DONE|FAILED
^S7F3_TASKS(niche_id,task_id,"lease")         = {owner_agent, owner_node, epoch, expires_at}
^S7F3_TASKS(niche_id,task_id,"dependency",n)  = other_task_id
^S7F3_TASKS(niche_id,task_id,"result_ref")    = ["S7F3_ARTIFACTS",artifact_id]
^S7F3_CONTEXT(context_id)                      = {kind, value_or_ref, version}
^S7F3_ARTIFACTS(artifact_id)                   = {mime, hash, body_or_uri}
^S7F3_EVENTS(seq)                              = {type, ref, agent_id, epoch, ts}
^S7F3_EVENTS("dedupe",idempotency_key)        = {event_seq, result_ref}
```

A task can link chains, patterns, decisions, wiki or Q&A through references to
`^S7F3_CONTEXT` and `^S7F3_ARTIFACTS`. The graph reachable from the niches
determines which content is part of the Space; unrelated cognitive objects
remain private on their node.

### Bootstrap between `node-a` and `node-b`

1. `node-a` creates the manifest and writes the initial generation in a single
   PDB transaction.
2. It grants `node-b` a macaroon `ns_prefix=S7F3_`, initially `op=read` and
   with a short expiry.
3. `node-a` sets a barrier with the `journal_seq` that covers all required
   Namespaces and delivers the manifest and the root hash to `node-b`.
4. `node-b` downloads each Namespace into a staging area. DDP still operates
   per Namespace; the Space orchestrator keeps a cursor for each member of the
   bundle.
5. `node-b` checks generation, hashes and references: every task must point to
   an existing niche and every required `result_ref` must resolve.
6. Only when all `required` trees reach the barrier does `node-b` mount
   `space-7f3` as active. It then receives incrementals from its cursors.
7. The authority issues separate write capabilities for the Namespaces the
   remote agent needs, for example `ns_prefix=S7F3_TASKS`; it does not have to
   grant write access over the whole family.

Staging is necessary because DDP does not currently apply an atomic batch that
spans several Namespaces. Without a barrier, `node-b` could observe a task
before receiving its niche, dependency or policy.

### Shared work

1. `planner-7` writes the task graph and publishes `task.ready`.
2. `researcher-2` receives the reference, checks dependencies and requests the
   lease for `T-18` from the authoritative node.
3. After obtaining `epoch=3`, it changes the status to `CLAIMED` and runs the
   task.
4. If it needs `T-12`, it leaves `T-18` in `WAITING` and its Job in `WAITING`;
   it does not poll actively.
5. The agent that finishes `T-12` writes its result and sends
   `dependency.ready` to `researcher-2`'s mailbox.
6. `researcher-2` revalidates the Namespace, generates an artifact and moves
   `T-18` to `REVIEW` using the same `epoch`.
7. `reviewer-4` checks the criteria. It writes `DONE` or creates a new revision
   with a different idempotent key.
8. The planner derives new tasks by reading events and results; it does not
   depend on a screen or a human action.

Both nodes materialize the kanban by walking `^S7F3_NICHES` and
`^S7F3_TASKS`. "Moving a card" is updating data in the Space and recording an
event; it is not a UI operation.

### Evolution toward routing and shared processes

Once the Space already shares data consistently, three optional layers are
added:

```text
^S7F3_CAPABILITIES(agent_id,capability) = {node_id, constraints, cost, ttl}
^S7F3_ROUTING(request_id)               = {task_ref, required, status, lease_epoch}
^S7F3_RUNS(run_id)                      = {task_ref, agent_id, node_id, status, epoch}
^S7F3_MIGRATION(run_id,generation)      = {snapshot_ref, hash, source, target, ack}
```

1. An agent creates a request in `^S7F3_ROUTING` pointing to a task.
2. The Space router picks a compatible offer and grants a lease.
3. The chosen node creates a local MVM Job and registers its logical identity
   in `^S7F3_RUNS`; the local `pid` never becomes a distributed identity.
4. If the Job waits for a dependency, it remains in `WAITING` or `HIBERNATE`.
   The DDP change wakes the router, which resolves `run_id → node_id → pid` and
   notifies the local mailbox.
5. To move it, the source stops the Job, exports only that state to
   `^S7F3_MIGRATION` and the target imports it with a new PID. `epoch` prevents
   both nodes from running the same `run_id`.

Neither `^STATE` nor `^PROCESSES` is replicated in full: they contain local MVM
state, PIDs and data belonging to other agents. The Space shares the logical
identity in `^S7F3_RUNS` and transfers only the selected snapshot during a
coordinated migration.

### Invariants

- The manifest is the authority over which Namespaces form the Space.
- A node does not activate a partially synchronized generation.
- A Space macaroon does not grant access to another Space prefix.
- A task has only one current lease.
- A result without the current `epoch` never moves to `DONE`.
- A dependency is referenced; it is not copied into each task.
- Reprocessing `task.ready` creates neither another task nor another effect.
- A `run_id` has a single current executing node even if its PID changes.

### Distance from the current storage

The thinking server currently persists niches and tasks in `^STATE` with flat
keys `global:niche:<id>` and `global:task:<id>`. In addition, its save routine
rebuilds the entire `STATE` Namespace through direct SQL, outside the DDP
journal. On a shared PDB, that full deletion can also remove `^STATE` rows
belonging to MVM Jobs. That layout does not allow isolating a Space,
authorizing a single niche, or coexisting safely with replicated MVM state.

Before implementing this case, storage must be migrated or dual-written to the
`^S7F3_*` family using operations that feed the journal, `space_id` must be
added to niches and tasks, and their cognitive references must be copied by
reachability. Replicating the current whole `^STATE` between nodes is not a
valid implementation of a shared Space.

## 5. A2A-02 — Pipeline of specialist agents

### Goal

An entry agent passes work to specialized agents — for example, classifier,
retriever, synthesizer and verifier — without chaining fragile synchronous
calls.

### Flow

1. The router creates `^S7F3_WORKFLOW(run_id,"step",step_id)` with inputs
   expressed as references to `^S7F3_CONTEXT`.
2. It publishes `step.ready` addressed to `capability:classify`.
3. The chosen agent claims the step by lease, writes the result and publishes
   `step.completed`.
4. The following agents wake up when all their dependencies are complete.
5. The verifier writes a reproducible verdict with the exact input and output
   references.

### Why use Namespace + mailbox

The Namespace preserves the DAG and allows it to be resumed after a restart.
The mailbox reduces latency, but any agent can recover pending work by walking
`^S7F3_WORKFLOW(run_id,"step",...)` with `$ORDER`.

## 6. A2A-03 — Shared memory and evidence

### Goal

Agents on different machines build a common base of facts without sending full
prompts or documents in every message.

```text
^S7F3_KNOWLEDGE("fact",fact_id)       = {claim, source_refs, confidence, hash}
^S7F3_KNOWLEDGE("relation",rel_id)    = {from, predicate, to}
^S7F3_EVIDENCE("source",source_id)    = {uri, content_hash, observed_at}
^S7F3_EVIDENCE("chunk",source_id,n)   = {text_or_blob_ref, embedding_ref}
^S7F3_KNOWLEDGE("revision",fact_id,n) = {agent_id, previous_hash, change, reason}
```

A collector publishes evidence; an extractor creates facts; a critic adds a
revision or a contradiction; a decision agent consumes only facts whose trust
policy is sufficient. Messages contain `fact_id` or `source_id`.

The deduplication key is the hash of the normalized content plus the operation
type. A revision never silently overwrites its provenance.

## 7. A2A-04 — Hibernation until required information exists

### Goal

An agent suspends processing for seconds, hours or days while another agent or
node produces a value it needs.

### Flow

1. The Job stores `wait_for={namespace,ref,min_version}` in its domain state.
2. It requests hibernation from the MVM; the MVM records the deadline in
   `^SCHEDULE` and moves the Job to `HIBERNATE`.
3. The producer writes the value and sends `fact.available` with its reference.
4. The owning node wakes the Job before the timeout. If the notice does not
   arrive, `^SCHEDULE` wakes it to re-evaluate the condition.
5. The Job reads the current version. If `min_version` is still not met, it
   renews the wait; if it is met, it continues from its persisted state.

A timeout does not imply failure: it is a durable opportunity to re-evaluate.
The condition lives in data, which is why it survives restarts and lost
messages.

## 8. A2A-05 — Moving an agent between nodes

### Goal

Move an execution from `node-a` to `node-b` for data affinity, cost, available
capacity or maintenance, without repeating instructions that were already
executed.

### Safe migration protocol

```text
^S7F3_MIGRATION(run_id,"request")  = {source, target, reason, requested_at}
^S7F3_MIGRATION(run_id,"lease")    = {owner_node, epoch, expires_at}
^S7F3_MIGRATION(run_id,"snapshot") = {hash, state_ref, code_ref, data_cursors}
^S7F3_MIGRATION(run_id,"status")   = PREPARE|TRANSFERRED|IMPORTED|COMMITTED|ABORTED
^S7F3_MIGRATION(run_id,"ack")      = {target_pid, target_node, epoch, snapshot_hash}
```

1. `node-a` moves the Job to `HALTED` at a cooperative point and stops renewing
   its execution lease.
2. It exports VM state, gas, mailbox and `wake_at`; it computes
   `snapshot_hash`.
3. DDP replicates the snapshot and the required data Namespaces to `node-b`.
4. `node-b` verifies hash, version and capabilities, acquires a new
   `lease.epoch` and imports the state with a new local PID.
5. If the Job was in `HIBERNATE`, `node-b` re-arms the remaining time. If it was
   in `WAITING`, it keeps the mailbox and the wait condition.
6. `node-b` publishes the ack and only then moves the migration to `COMMITTED`.
7. `node-a` invalidates its copy. It may keep the snapshot for auditing, but it
   must never run it again with an earlier `epoch`.

### Critical rule

Export/import already exists in the MVM. The full coordination of `HALTED`,
lease, fencing, DDP transfer and ack is an orchestration protocol that must be
implemented on top. Copying `^STATE` without that protocol can run the same
agent on two nodes.

## 9. A2A-06 — Failover after losing a node

### Goal

Resume on another node an agent whose node stopped emitting a heartbeat.

### Flow

1. Each node publishes a heartbeat with an expiry in `^PRESENCE(node_id)`.
2. The agent supervisor detects that both the heartbeat and the execution lease
   have expired. It does not take control before both expiries.
3. It selects the last confirmed snapshot and the associated DDP cursor.
4. It grants a higher `epoch` to the replacement node.
5. The replacement imports, re-evaluates any pending effect through its
   idempotent key and continues.
6. If the old node reappears, it observes that its `epoch` is stale and stops
   itself.

The recovery goal is **at-least-once without duplicated effects**, not magical
exactly-once. Idempotency turns the retry into a safe operation.

## 10. A2A-07 — Capability discovery and routing

### Goal

An agent automatically finds another agent able to run a task on a suitable
node.

```text
^S7F3_CAPABILITIES(agent_id,capability) = {version, constraints, cost, ttl}
^PRESENCE(agent_id)                    = {node_id, load, status, heartbeat_at}
^S7F3_ROUTING(request_id)              = {required, input_ref, policy, status}
```

The router filters out unexpired offers, validates that the agent can read the
input Namespaces and scores locality, load and cost. It issues a grant with a
TTL; if it receives no ack, it grants to another candidate using a higher
`epoch`.

Secrets must not be advertised in `^S7F3_CAPABILITIES`. The offer declares
capability names; the actual authorization is decided by the macaroon issued
for that `request_id`.

## 11. A2A-08 — Autonomous incident response

### Goal

Observation, diagnosis and repair agents coordinate an incident across
machines without a single long-running process concentrating all the context.

### Flow

1. The detector creates `^S7F3_INCIDENTS(id,"observation",n)` with immutable
   evidence in `^S7F3_EVIDENCE`.
2. The correlation agent groups observations and creates hypotheses.
3. Diagnosis agents claim different hypotheses in parallel.
4. The policy agent selects a permitted action and issues a macaroon limited to
   the Namespace and to the duration of the repair.
5. The repairer records `intent`, `epoch` and `idempotency_key` before the
   effect.
6. An independent verifier compares subsequent metrics and marks `RESOLVED`,
   `ROLLBACK` or `ESCALATE_TO_AGENT`.

`ESCALATE_TO_AGENT` means delegating to another agent with more capacity or
permissions, not requesting human intervention. Irreversible actions still
require an explicit authorization policy defined by the agent network.

## 12. Conformance criteria for these cases

An A2A implementation is considered valid when it demonstrates:

1. two nodes mount the same generation of a Space and recover all its required
   Namespaces;
2. repeating a DDP batch does not duplicate tasks, events or external effects;
3. a duplicated message only causes one idempotent re-read;
4. a Job in `HIBERNATE` consumes no slices and keeps its `wake_at` when
   migrating;
5. an imported Job keeps its IP, frames, variables, mailbox and gas;
6. two nodes that believe they are owners cannot both publish successfully,
   because only the current `epoch` is accepted;
7. a node restored with an old lease stops itself;
8. an agent can only read or write the family or Namespace authorized by its
   macaroon;
9. losing the mailbox does not lose the work, because the Namespace allows it
   to be rebuilt;
10. no flow needs a session, a screen or a human decision to progress to its
    terminal state.

## 13. What is available and what remains to be closed

| Capability | Current status |
|------------|----------------|
| Hierarchical globals, `$ORDER`, transactions and `$LOCK` | Implemented |
| DDP journal with `seq`, cursors, retry and anti-loop | Implemented |
| Macaroons by Namespace and operation | Implemented |
| Durable mailbox and waking from `WAITING` | Implemented |
| `HIBERNATE`, `^SCHEDULE` and restores remaining time | Implemented |
| Export/import of MVM state | Implemented |
| A2A envelope convention and idempotency keys | Contract proposed here |
| Namespace family and Space manifest | Contract proposed here |
| Thinking schema with `space_id` outside the monolithic `^STATE` | Pending |
| Multi-Namespace bootstrap with staging, barrier and root hash | Pending orchestrator |
| Router `agent_id → node_id → pid` over `^PRESENCE` | Pending orchestrator |
| Authoritative lease and fencing across nodes | Pending orchestrator |
| Coordinated DDP migration with ack and rollback | Pending orchestrator |
| Multi-node conformance of the ten criteria above | Pending |

The next product piece is not another interface for people: it is the A2A
orchestrator that turns the existing primitives into ownership, hibernation and
safe migration across machines.
