#!/usr/bin/env python3
"""
LUMEN Sequential Thinking MCP Server — structured reasoning engine.

A reasoning notebook for LLMs. Instead of thinking inside the context window
(where thoughts get compressed and lost), the LLM writes thoughts to this
external tool that persists them, enables revision, branching, and analysis.

Enhanced with:
  - TF-IDF semantic similarity (zero deps, pure Python)
  - Contradiction detection
  - Automatic clustering by theme
  - Chain-to-plan conversion
  - Cross-chain bridging (knowledge reuse across sessions)

LUMEN benefits: 60-80% wire savings (highly structured data),
                 multi-agent shared reasoning, streaming for long chains.

Hermes config:
  mcp_servers:
    lumen_thinking:
      command: "python"
      args: ["server.py"]
      transport: lumen
"""

from __future__ import annotations

import sys
import json
import os
import re
import math
import time
from collections import defaultdict, Counter
from pathlib import Path
from typing import Any

# ── Windows: force UTF-8 on stdout so emoji don't break MCP pipes ──
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

def _safe_print(msg: str) -> None:
    """Print to stderr so it doesn't interfere with JSON-RPC on stdout."""
    try:
        print(msg, file=sys.stderr, flush=True)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════
# Data Model — Multi-agent session isolation
# ═══════════════════════════════════════════════════════════════════════

class Session:
    """Per-agent isolated state: chains, assumptions, model, work log."""
    def __init__(self, label: str = ""):
        self.label = label
        self.chains: dict[str, dict] = {}
        self.assumptions: list[dict] = []
        self.next_assumption_id = 1
        self.model: dict[str, dict] = {}
        self.works: list[dict] = []
        self.next_work_id = 1
        self.patterns: list[dict] = []
        self.next_pattern_id = 1
        self.decisions: list[dict] = []
        self.next_decision_id = 1
        self.bridges: list[dict] = []  # thought_bridge results
        self.wiki: dict[str, dict] = {}  # named wiki pages: title → {content, created_at, updated_at, author}
        self.model_name: str = ""  # LLM model used in this session
        self.tool_calls = 0
        self.created_at = time.time()
        self.updated_at = time.time()

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "chains": self.chains,
            "assumptions": self.assumptions,
            "next_assumption_id": self.next_assumption_id,
            "model": self.model,
            "works": self.works,
            "next_work_id": self.next_work_id,
            "patterns": self.patterns,
            "next_pattern_id": self.next_pattern_id,
            "decisions": self.decisions,
            "next_decision_id": self.next_decision_id,
            "bridges": self.bridges,
            "wiki": self.wiki,
            "model_name": self.model_name,
            "tool_calls": self.tool_calls,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls(label=d.get("label", ""))
        s.chains = d.get("chains", {})
        s.assumptions = d.get("assumptions", [])
        s.next_assumption_id = d.get("next_assumption_id", 1)
        s.model = d.get("model", {})
        s.works = d.get("works", [])
        s.next_work_id = d.get("next_work_id", 1)
        s.patterns = d.get("patterns", [])
        s.next_pattern_id = d.get("next_pattern_id", 1)
        s.decisions = d.get("decisions", [])
        s.next_decision_id = d.get("next_decision_id", 1)
        s.bridges = d.get("bridges", [])
        s.wiki = d.get("wiki", {})
        s.model_name = d.get("model_name", "")
        s.tool_calls = d.get("tool_calls", 0)
        s.created_at = d.get("created_at", time.time())
        s.updated_at = d.get("updated_at", time.time())
        return s

_sessions: dict[str, Session] = {}  # session_id → Session
_DEFAULT_SESSION = "default"
_next_session_num = 1

# ═══════════════════════════════════════════════════════════════════════
# State Persistence — survives server restarts
# ═══════════════════════════════════════════════════════════════════════

_STATE_FILE = Path(__file__).parent / ".thinking_state.json"
_SAVE_INTERVAL = 10  # auto-save every N tool calls
_save_counter = 0
_last_state_mtime = 0.0  # track when we last read the state file
_loaded_from_disk = False
_call_timeline: list[dict] = []
_lumen_ws = None  # LUMEN WebSocket server instance
_session_presence: dict = {}
_file_touches: list[dict] = []  # [{session_id, path, timestamp}]
_file_claims: dict = {}  # {filepath: {owner, expires_at, status, requests[]}}  # session_id → {pid, last_seen, tool_calls}
_agent_messages: list[dict] = []  # [{from_session, to_session, content, timestamp}]
_global_patterns: list[dict] = []  # patterns shared across all sessions

def _save_state() -> None:
    """Persist all state to disk atomically."""
    global _save_counter
    _save_counter = 0
    try:
        # Record timeline snapshot with hourly bucketing
        total_calls = sum(s.tool_calls for s in _sessions.values())
        now = time.time()
        hour_key = int(now // 3600)  # bucket by hour
        
        # Find or create this hour's bucket
        if _call_timeline and _call_timeline and isinstance(_call_timeline[-1], dict) and _call_timeline[-1].get("hour") == hour_key:
            _call_timeline[-1]["calls"] = total_calls
            _call_timeline[-1]["ts"] = now
        else:
            _call_timeline.append({"hour": hour_key, "ts": now, "calls": total_calls, "delta": total_calls - (_call_timeline[-1].get("calls", 0) if _call_timeline else 0)})
        
        # Keep last 48h (48 buckets)
        cutoff_hour = hour_key - 48
        _call_timeline[:] = [b for b in _call_timeline if b["hour"] > cutoff_hour]
        # Keep last 200 snapshots (~30min at 10s intervals)
        if len(_call_timeline) > 200:
            _call_timeline[:] = _call_timeline[-200:]
        
        state = {
            "sessions": {sid: s.to_dict() for sid, s in _sessions.items()},
            "next_session_num": _next_session_num,
            "preserved": _preserved,
            "timeline": _call_timeline,
            "presence": {sid: {"pid": os.getpid(), "last_seen": time.time(), "tool_calls": s.tool_calls, "model": s.model_name or "unknown"} for sid, s in _sessions.items()},
            "file_touches": _file_touches[-200:],
            "file_claims": _file_claims,
            "agent_messages": _agent_messages[-100:],  # last 100 messages
            "global_patterns": _global_patterns[-300:],  # last 300 global patterns
            "saved_at": time.time(),
        }
        tmp = str(_STATE_FILE) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, str(_STATE_FILE))
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to save state: {e}")

def _load_state() -> bool:
    """Restore state from disk. Returns True if state was loaded."""
    global _sessions, _next_session_num, _preserved, _loaded_from_disk
    if not _STATE_FILE.exists():
        _safe_print("[lumen-thinking] No saved state found — starting fresh.")
        return False
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        _sessions = {sid: Session.from_dict(sd) for sid, sd in state.get("sessions", {}).items()}
        _next_session_num = state.get("next_session_num", 1)
        _preserved = state.get("preserved", [])
        if "timeline" in state:
            _call_timeline[:] = state["timeline"]
        global _agent_messages, _global_patterns
        _agent_messages = state.get("agent_messages", [])
        _global_patterns = state.get("global_patterns", [])
        _loaded_from_disk = True
        global _file_claims
        _file_claims = state.get("file_claims", {})
        _last_state_mtime = _STATE_FILE.stat().st_mtime if _STATE_FILE.exists() else 0.0
        total_chains = sum(len(s.chains) for s in _sessions.values())
        total_patterns = sum(len(s.patterns) for s in _sessions.values())
        saved_at = state.get("saved_at", "unknown")
        # Recompute global assumption ID counter to avoid collisions after restore
        max_id = 0
        for s in _sessions.values():
            for a in s.assumptions:
                if a.get("id", 0) > max_id:
                    max_id = a["id"]
        global _next_assumption_id
        _next_assumption_id = max_id + 1
        _safe_print(f"[lumen-thinking] State restored: {total_chains} chains, {total_patterns} patterns, "
                     f"{len(_preserved)} preserved items across {len(_sessions)} sessions "
                     f"(saved {saved_at})")
        return True
    except Exception as e:
        _safe_print(f"[lumen-thinking] Failed to load state: {e} — starting fresh.")
        return False

def _auto_save() -> None:
    """Called after each tool call. Saves every _SAVE_INTERVAL calls."""
    global _save_counter
    _save_counter += 1
    if _save_counter >= _SAVE_INTERVAL:
        _save_state()

def _get_session(session_id: str | None = None) -> Session:
    """Get or create a session. None → default session."""
    sid = session_id or _DEFAULT_SESSION
    if sid not in _sessions:
        _sessions[sid] = Session(label=sid)
    _sessions[sid].updated_at = time.time()
    _sessions[sid].tool_calls += 1
    _auto_save()  # persist state periodically (works for both server.py and server_shm.py)
    return _sessions[sid]

def _new_chain(session: Session) -> str:
    """Create a new chain in a session. Returns chain_id."""
    cid = f"chain_{len(session.chains) + 1}_{int(time.time())}"
    session.chains[cid] = _new_chain_dict(cid)
    return cid

def _new_chain_dict(cid: str) -> dict:
    """Create a new chain dict without adding to session."""
    return {
        "thoughts": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "version": 1,
    }

def _prune_old(session: Session, n: int = 10) -> None:
    """Keep only the N most recently updated chains. Never prune named chains (custom IDs)."""
    if len(session.chains) <= n:
        return
    # Named chains: custom IDs (not matching chain_N_* auto-generated pattern)
    import re as _re
    auto_pattern = _re.compile(r'^chain_\d+_\d+$')
    named = {cid: c for cid, c in session.chains.items() if not auto_pattern.match(cid)}
    auto = {cid: c for cid, c in session.chains.items() if auto_pattern.match(cid)}
    # If we can keep all named + some auto, do that
    named_count = len(named)
    if named_count >= n:
        # Too many named chains — keep newest N named, drop all auto
        keep_named = dict(sorted(named.items(), key=lambda kv: kv[1]["updated_at"], reverse=True)[:n])
        session.chains = keep_named
    else:
        # Keep all named + fill remaining slots with newest auto
        slots_left = n - named_count
        keep_auto = dict(sorted(auto.items(), key=lambda kv: kv[1]["updated_at"], reverse=True)[:slots_left])
        session.chains = {**named, **keep_auto}

# Legacy compatibility: alias globals to default session properties
def _chains() -> dict: return _get_session().chains
def _assumptions() -> list: return _get_session().assumptions
def _model() -> dict: return _get_session().model
def _works() -> list: return _get_session().works


# ═══════════════════════════════════════════════════════════════════════
# TF-IDF Engine (stdlib only — no numpy, scipy, or API deps)
# ═══════════════════════════════════════════════════════════════════════

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "can", "shall", "this", "that",
    "it", "its", "i", "me", "my", "we", "our", "you", "your", "he", "she",
    "they", "them", "not", "no", "if", "so", "as", "just", "about", "into",
    "through", "during", "before", "after", "above", "below", "between",
})


def _tokenize(text: str) -> list[str]:
    """Tokenize: lowercase, split on non-alpha, remove stopwords & short tokens."""
    tokens = re.findall(r"[a-záéíóúñ]{3,}", text.lower())
    return [t for t in tokens if t not in _STOPWORDS]


def _build_tfidf(thoughts: list[dict]) -> tuple[list[dict[str, float]], dict[str, float]]:
    """
    Build TF-IDF vectors for a list of thoughts.
    Returns (vectors, idf) where each vector is {term: tfidf_score}.
    """
    if not thoughts:
        return [], {}

    # Tokenize all thoughts
    docs = [_tokenize(t["thought"]) for t in thoughts]
    N = len(docs)

    # Document frequency per term
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for term in set(doc):
            df[term] += 1

    # IDF
    idf = {term: math.log((N + 1) / (freq + 1)) + 1.0 for term, freq in df.items()}

    # TF-IDF vectors
    vectors = []
    for doc in docs:
        tf = Counter(doc)
        vec = {}
        norm = 0.0
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                vec[term] = score
                norm += score * score
        # L2 normalize
        norm = math.sqrt(norm) if norm > 0 else 1.0
        vectors.append({t: s / norm for t, s in vec.items()})
    return vectors, idf


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF-IDF vectors."""
    if not a or not b:
        return 0.0
    # Both are already L2-normalized, so dot product = cosine
    common = set(a) & set(b)
    return sum(a[t] * b[t] for t in common)


def _sentiment_heuristic(text: str) -> float:
    """Simple lexicon-free sentiment heuristic (-1 to +1)."""
    positive = {"mejor", "bueno", "excelente", "correcto", "funciona", "solución", "éxito", "good", "great", "excellent", "correct", "works", "perfect", "perfectly", "reliable", "robust", "success", "successful", "optimal", "safe", "secure", "stable", "zero", "never",
                "eficiente", "óptimo", "recomiendo", "viable", "seguro", "robusto"}
    negative = {"error", "errors", "fail", "fails", "failure", "failing", "bug", "bugs", "broken", "crash", "crashes", "down", "downtime", "outage", "fallo", "falla", "incorrecto", "problema", "rompe", "riesgo",
                "lento", "peligroso", "fracaso", "inviable", "débil", "frágil", "no"}
    tokens = _tokenize(text)
    pos = sum(1 for t in tokens if t in positive)
    neg = sum(1 for t in tokens if t in negative)
    total = len(tokens) or 1
    return (pos - neg) / max(total, 1)


# ═══════════════════════════════════════════════════════════════════════
# Tool definitions
# ═══════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "sequential_thinking",
        "description": "A structured thinking tool for dynamic and reflective problem-solving. Break down complex problems into manageable steps, revise earlier thoughts, branch into alternative reasoning paths, and verify hypotheses. Each thought is stored externally, surviving context compression.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "The current thinking step"},
                "nextThoughtNeeded": {"type": "boolean", "description": "Whether another thought step is needed after this one"},
                "thoughtNumber": {"type": "integer", "description": "Current thought number (1-based). Auto-generated if not provided.", "minimum": 1},
                "totalThoughts": {"type": "integer", "description": "Estimated total thoughts needed. Can be adjusted dynamically.", "minimum": 1},
                "isRevision": {"type": "boolean", "description": "Whether this revises a previous thought", "default": False},
                "revisesThought": {"type": "integer", "description": "Which thought number is being revised (required if isRevision=true)", "minimum": 1},
                "branchFromThought": {"type": "integer", "description": "Branch from this thought number to explore an alternative path", "minimum": 1},
                "branchId": {"type": "string", "description": "Identifier for this branch (e.g. 'alternative-plan')"},
                "needsMoreThoughts": {"type": "boolean", "description": "Set true to increase totalThoughts estimate", "default": False},
                "chainId": {"type": "string", "description": "ID of an existing chain to continue. Omit to create a new chain."},
                "verbose": {"type": "boolean", "description": "Show full recent history (default: false = compact mode, shows only last thought)", "default": False}
            },
            "required": ["thought", "nextThoughtNeeded", "totalThoughts"]
        }
    },
    {
        "name": "thought_similarity",
        "description": "Find semantically similar thoughts in a chain using TF-IDF cosine similarity. Helps avoid repeating ideas and identifies related concepts across the reasoning chain. Zero external dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to search in"},
                "thought": {"type": "string", "description": "Thought to find similar matches for"},
                "topN": {"type": "integer", "description": "Number of similar thoughts to return (default: 3)", "default": 3, "maximum": 10},
                "minScore": {"type": "number", "description": "Minimum similarity score 0-1 (default: 0.1)", "default": 0.1}
            },
            "required": ["chainId", "thought"]
        }
    },
    {
        "name": "thought_contradiction",
        "description": "Detect thoughts in a chain that semantically contradict a given thought. Uses TF-IDF similarity with sentiment analysis to flag potential inconsistencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to check"},
                "thought": {"type": "string", "description": "Thought to check for contradictions against"}
            },
            "required": ["chainId", "thought"]
        }
    },
    {
        "name": "thought_summarize",
        "description": "Summarize a reasoning chain into a condensed overview. Groups thoughts by semantic cluster and provides a high-level summary of each cluster.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to summarize"},
                "maxClusters": {"type": "integer", "description": "Max number of theme clusters (default: 5)", "default": 5, "maximum": 10}
            },
            "required": ["chainId"]
        }
    },
    {
        "name": "thought_to_plan",
        "description": "Convert a reasoning chain into an actionable plan. Extracts concrete steps, identifies dependencies, and formats as a structured task list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID to convert into a plan"},
                "format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format (default: markdown)", "default": "markdown"}
            },
            "required": ["chainId"]
        }
    },
    {
        "name": "thought_evaluate",
        "description": "Evaluate the quality of a thought within a chain. Scores consistency, specificity, and actionability. Provides constructive feedback for improvement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain ID containing the thought"},
                "thoughtNumber": {"type": "integer", "description": "Thought number to evaluate", "minimum": 1}
            },
            "required": ["chainId", "thoughtNumber"]
        }
    },
    {
        "name": "thought_bridge",
        "description": "Find semantically related thoughts across DIFFERENT reasoning chains. Enables knowledge reuse: 'What did I think about this topic in a previous session?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "Thought to find cross-chain connections for"},
                "topN": {"type": "integer", "description": "Max cross-chain connections (default: 3)", "default": 3, "maximum": 5}
            }
        }
    },
    {
        "name": "assume",
        "description": "Explicitly record an assumption you are making. This EXPANDS your awareness of blind spots — it does NOT make decisions for you. The user can review and correct your assumptions. Use this when solving problems: 'I'm assuming X. Let me write that down so we can verify it later.'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "statement": {"type": "string", "description": "The assumption you are making (e.g. 'the bug is in auth.py')"},
                "category": {"type": "string", "description": "Category: 'bug_location', 'user_env', 'dependency', 'performance', 'security', 'design', 'other'", "default": "other"},
                "confidence_note": {"type": "string", "description": "Why you think this might be true (e.g. 'based on error trace', 'user mentioned Windows')"}
            },
            "required": ["statement"]
        }
    },
    {
        "name": "list_assumptions",
        "description": "List all recorded assumptions. Shows which are confirmed, refuted, or unverified. Use this to review your blind spots before acting on them.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all", "unverified", "confirmed", "refuted"], "description": "Filter by status (default: unverified)", "default": "unverified"},
                "category": {"type": "string", "description": "Filter by category"}
            }
        }
    },
    {
        "name": "check_assumption",
        "description": "Mark an assumption as confirmed or refuted after verification. Use this to close the loop: 'I assumed X — let me check... confirmed!' This builds a track record of your accuracy without automating decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assumption_id": {"type": "integer", "description": "ID of the assumption to check"},
                "outcome": {"type": "string", "enum": ["confirmed", "refuted"], "description": "Was the assumption correct?"},
                "evidence": {"type": "string", "description": "What evidence confirmed or refuted it"}
            },
            "required": ["assumption_id", "outcome"]
        }
    },
    {
        "name": "model_add",
        "description": "Add a file or directory to the project mental model. Build a living map of the project so the agent understands its structure without re-reading everything. This is purely FACTUAL — no opinions or automation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or directory path (relative to project root)"},
                "role": {"type": "string", "description": "What this file does: 'authentication', 'database', 'config', 'api', 'model', 'test', 'util', 'entry_point', 'other'"},
                "deps": {"type": "array", "items": {"type": "string"}, "description": "List of files this depends on"},
                "notes": {"type": "string", "description": "Brief note about this file (e.g. 'Handles JWT token validation')"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "model_query",
        "description": "Query the project mental model. Ask: 'what files depend on X?', 'what role does Y have?', 'what would break if I change Z?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to ask: 'deps of <path>', 'dependents of <path>', 'role=<role>', 'impact of <path>', 'all'"},
                "target": {"type": "string", "description": "File path or role name to query about"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "model_stats",
        "description": "Get statistics about the project mental model: how many files are mapped, what roles exist, dependency density.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "model_map",
        "description": "Generate a visual tree map of the project from the mental model. Shows files, their roles, and dependency relationships.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_path": {"type": "string", "description": "Root directory to start the map from (default: project root)", "default": "."},
                "max_depth": {"type": "integer", "description": "Max depth to show (default: 3)", "default": 3, "maximum": 5}
            }
        }
    },
    {
        "name": "model_remove",
        "description": "Remove a file from the mental model when it's deleted or no longer relevant. Automatically updates all dependency links.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to remove from the model"}
            },
            "required": ["path"]
            }
            },
            {
            "name": "model_scan",
            "description": "Auto-scan a directory and build an initial mental model. Discovers files, guesses roles by filename (e.g. 'auth.py' -> 'authentication'), and detects Python imports for dependencies. Use this to bootstrap the model for a new project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root_dir": {"type": "string", "description": "Directory to scan (default: current working directory)", "default": "."},
                    "max_depth": {"type": "integer", "description": "Max directory depth (default: 2, max: 4)", "default": 2, "maximum": 4},
                    "file_glob": {"type": "string", "description": "File pattern to match (default: '*.py')", "default": "*.py"},
                    "limit": {"type": "integer", "description": "Max files to scan (default: 200)", "default": 200}
                }
            }
            },
            {
            "name": "context_preserve",
        "description": "Mark a piece of information as critical to preserve. Use when you discover something important that MUST survive context compression: a key finding, a user preference, a decision rationale, a bug root cause. This is your 'don't forget this' tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The information to preserve"},
                "priority": {"type": "string", "enum": ["critical", "high", "medium"], "description": "How critical is this? (default: high)", "default": "high"},
                "category": {"type": "string", "description": "Category: 'finding', 'decision', 'user_pref', 'bug_cause', 'architecture', 'todo', 'other'", "default": "other"}
            },
            "required": ["content"]
        }
    },
    {
        "name": "context_check",
        "description": "Check what information has been preserved and assess decay risk. Shows the preservation list with priorities, suggests what might be at risk of being lost. Use this when the conversation gets long or before a context compression event.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_items": {"type": "integer", "description": "Max items to show (default: 20)", "default": 20}
            }
        }
    },
    {
        "name": "work_start",
        "description": "Start tracking a work item. Use when beginning a task: 'I'm starting X'. Survives across sessions (persists in local JSON file) — unlike Hermes built-in todo which is per-session. This is purely FACTUAL: what you're doing, not how to do it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "description": "What you're working on (e.g. 'fix auth bug #42')"},
                "category": {"type": "string", "description": "Category: 'bug', 'feature', 'refactor', 'docs', 'review', 'other'", "default": "other"}
            },
            "required": ["item"]
        }
    },
    {
        "name": "work_block",
        "description": "Mark a work item as blocked. Use when you can't continue because you're waiting for something: PR review, user feedback, dependency. The agent can later check what's blocked and follow up.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_id": {"type": "integer", "description": "ID of the work item to mark as blocked"},
                "reason": {"type": "string", "description": "Why it's blocked (e.g. 'waiting for PR review from Nous')"}
            },
            "required": ["work_id", "reason"]
        }
    },
    {
        "name": "work_done",
        "description": "Mark a work item as completed. Use when you finish something: 'Done with X'. Records completion for future reference. The agent can see what was accomplished in past sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "work_id": {"type": "integer", "description": "ID of the work item to mark as done"},
                "result": {"type": "string", "description": "What was the outcome? (e.g. 'PR merged', 'bug fixed in commit abc123')"}
            },
            "required": ["work_id"]
        }
    },
    {
        "name": "work_log",
        "description": "Show the work log: what's in progress, blocked, done. Filterable by status. Survives across sessions — gives the agent continuity when resuming work.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["all", "in_progress", "blocked", "done"], "description": "Filter by status (default: all)", "default": "all"},
                "limit": {"type": "integer", "description": "Max items to show (default: 20)", "default": 20}
            }
        }
    },
    {
        "name": "context_estimate",
        "description": "Estimate how much context is being used and suggest what to externalize. Based on session activity: tool call count, response sizes, task complexity. Does NOT measure actual tokens — this is a heuristic. Helps the agent be proactive about offloading before context compression hits.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "session_init",
        "description": "Create or retrieve a multi-agent session. Sessions isolate chains, assumptions, models, and work logs so multiple agents can share a transport without state collisions. Returns a session_id for use in other tool calls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "Human-friendly session label (e.g. 'agent-a', 'code-review')"},
                "session_id": {"type": "string", "description": "Existing session ID to resume. Creates a new one if omitted."}
            }
        }
    },
    {
        "name": "session_list",
        "description": "List all active sessions with their stats (chains, assumptions, model size, tool calls).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "agent_message",
        "description": "Send a message to another agent session. Enables cross-session coordination between Hermes instances working on related tasks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_session": {"type": "string", "description": "Target session ID or label to send message to"},
                "content": {"type": "string", "description": "Message content to send"},
                "priority": {"type": "string", "description": "Message priority: 'normal', 'high', 'urgent'", "default": "normal"}
            },
            "required": ["to_session", "content"]
        }
    },
    {
        "name": "agent_inbox",
        "description": "Read messages sent to this agent session from other Hermes instances. Returns unread messages by default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max messages to return (default: 20, max: 50)", "default": 20},
                "unread_only": {"type": "boolean", "description": "Only return unread messages", "default": False}
            }
        }
    },
    {
        "name": "collision_check",
        "description": "Check for file collisions between active sessions. Detects when multiple sessions are modifying the same files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_seconds": {"type": "integer", "description": "Time window in seconds (default: 300)", "default": 300}
            }
        }
    },
    {
        "name": "pattern_record",
        "description": "Record a recurring bug pattern, anti-pattern, or fix strategy. Builds institutional memory across sessions so the agent recognizes problems it has solved before. Patterns survive context compression and are matchable via pattern_match.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern_name": {"type": "string", "description": "Short name (e.g. 'null-check-in-async-callback')"},
                "description": {"type": "string", "description": "What the pattern looks like and why it's a problem"},
                "code_snippet": {"type": "string", "description": "Example code showing the pattern (optional)"},
                "fix_strategy": {"type": "string", "description": "How to fix it (e.g. 'add null guard before await')"},
                "category": {"type": "string", "description": "Category: 'bug', 'security', 'performance', 'design', 'testing', 'other'", "default": "bug"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Searchable tags (e.g. ['async', 'null', 'javascript'])"}
            },
            "required": ["pattern_name", "description"]
        }
    },
    {
        "name": "pattern_match",
        "description": "Search recorded patterns for matches against a problem description or code snippet. Uses TF-IDF semantic similarity to find relevant patterns. Helps the agent recognize: 'Have I seen this bug before?'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Problem description or code snippet to match against patterns"},
                "category": {"type": "string", "description": "Filter by category"},
                "min_score": {"type": "number", "description": "Minimum similarity score 0-1 (default: 0.1)", "default": 0.1},
                "top_n": {"type": "integer", "description": "Max patterns to return (default: 3)", "default": 3}
            },
            "required": ["description"]
        }
    },
    {
        "name": "decision_log",
        "description": "Record a design or implementation decision with its rationale. Tracks WHAT was decided, WHY, and what alternatives were considered. Decision logs persist across sessions, preventing repeated debates about already-settled questions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "description": "What was decided (e.g. 'Use SQLite instead of PostgreSQL for local cache')"},
                "rationale": {"type": "string", "description": "Why this decision (e.g. 'Zero setup for users, no Docker dependency')"},
                "alternatives": {"type": "array", "items": {"type": "string"}, "description": "Alternatives considered and why rejected"},
                "context": {"type": "string", "description": "What was the situation when this decision was made?"},
                "category": {"type": "string", "description": "Category: 'architecture', 'tooling', 'dependency', 'api', 'performance', 'security', 'other'", "default": "other"},
                "revisit_trigger": {"type": "string", "description": "Condition that would make this worth revisiting (e.g. 'If we need multi-user support')"}
            },
            "required": ["decision", "rationale"]
        }
    },
    {
        "name": "decision_list",
        "description": "List all recorded decisions, newest first.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Filter by category"}
            }
        }
    },
    {
        "name": "state_snapshot",
        "description": "Ultra-compact system health: returns chain count, thought count, avg score, pattern count, work count, and total tool calls in ONE line. No detail.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "thought_compress",
        "description": "Compress a reasoning chain to N key thoughts (default 3). Selects first, last, and top-scored middle thoughts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain to compress"},
                "targetThoughts": {"type": "integer", "default": 3, "maximum": 10}
            },
            "required": ["chainId"]
        }
    },
    {
        "name": "chain_diff",
        "description": "Show only what changed between two points: additions, revisions, and branches count.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "chainId": {"type": "string", "description": "Chain to diff"},
                "from": {"type": "integer", "default": 1},
                "to": {"type": "integer"}
            },
            "required": ["chainId"]
        }
    },
    {
        "name": "tool_cache",
        "description": "Cache expensive results. SET: tool_cache(key, value, ttl). GET: tool_cache(key).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Cache key"},
                "value": {"type": "string", "description": "Value to cache (SET mode)"},
                "ttl": {"type": "integer", "default": 300}
            },
            "required": ["key"]
        }
    },
    {
        "name": "batch_call",
        "description": "Execute multiple tools in sequence, returning ONE compact output line.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tools": {"type": "array", "items": {"type": "object"}, "description": "List of {name, args} objects"}
            },
            "required": ["tools"]
        }
    }
]


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════

def tool_sequential_thinking(args: dict) -> dict:
    """Core: record a thought in a reasoning chain."""
    session = _get_session(args.get("session_id"))
    thought_text = args["thought"]
    next_needed = args["nextThoughtNeeded"]
    total_thoughts = args["totalThoughts"]
    thought_number = args.get("thoughtNumber")
    is_revision = args.get("isRevision", False)
    revises = args.get("revisesThought")
    branch_from = args.get("branchFromThought")
    branch_id = args.get("branchId")
    needs_more = args.get("needsMoreThoughts", False)
    chain_id = args.get("chainId")

    # Auto-create chain if needed
    if not chain_id:
        chain_id = _new_chain(session)
    elif chain_id not in session.chains:
        # Auto-create with custom ID on first use
        session.chains[chain_id] = _new_chain_dict(chain_id)

    chain = session.chains[chain_id]

    # Auto-number if not provided
    if thought_number is None:
        thought_number = len(chain["thoughts"]) + 1
    elif needs_more:
        total_thoughts = max(total_thoughts, thought_number + 1)

    thought_obj = {
        "number": thought_number,
        "thought": thought_text,
        "totalThoughts": total_thoughts,
        "nextThoughtNeeded": next_needed,
        "isRevision": is_revision,
        "revisesThought": revises,
        "branchFromThought": branch_from,
        "branchId": branch_id,
        "timestamp": time.time(),
    }

    # If revision, mark original
    if is_revision and revises:
        for t in chain["thoughts"]:
            if t["number"] == revises:
                t["revisedBy"] = thought_number
                break

    chain["thoughts"].append(thought_obj)
    chain["updated_at"] = time.time()
    chain["version"] += 1
    _prune_old(session)

    # Build response with context
    summary_lines = [
        f"✅ Thought #{thought_number} recorded in chain '{chain_id}'",
        f"   Total thoughts: {len(chain['thoughts'])} / {total_thoughts}",
    ]
    if is_revision:
        summary_lines.append(f"   🔄 Revision of thought #{revises}")
    if branch_from:
        summary_lines.append(f"   🌿 Branch from thought #{branch_from}" + (f" ({branch_id})" if branch_id else ""))
    if next_needed:
        summary_lines.append(f"   ➡️  Next thought expected (totalThoughts={total_thoughts})")
    else:
        summary_lines.append(f"   🏁 Chain complete ({len(chain['thoughts'])} thoughts)")

    # Show recent thoughts for context — compact mode (default)
    verbose = args.get("verbose", False)
    if verbose and chain["thoughts"]:
        summary_lines.append(f"\n   Recent thoughts:")
        for t in chain["thoughts"][-5:]:
            marker = "🔄" if t.get("isRevision") else "🌿" if t.get("branchFromThought") else "  "
            summary_lines.append(f"   {marker} #{t['number']}: {t['thought'][:80]}...")
    elif chain["thoughts"]:
        # Compact: just show last thought
        last = chain["thoughts"][-1]
        summary_lines.append(f"   Last: #{last['number']}: {last['thought'][:100]}")

    # Auto-trigger: evaluate thought quality automatically
    if len(chain["thoughts"]) >= 3 and not new_thought.get("score"):
        try:
            from server import tool_thought_evaluate as _eval
            _ = __import__('server', fromlist=['_sessions', '_DEFAULT_SESSION'])
            # Direct evaluation — set score on the thought
            thought_text = new_thought["thought"]
            specificity = min(len(thought_text) / 200, 1.0)
            has_action = any(w in thought_text.lower() for w in
                ["hacer", "crear", "ejecutar", "analizar", "implementar",
                 "migrar", "configurar", "build", "deploy", "run", "test",
                 "create", "execute", "analyze", "fix", "add", "update", "remove",
                 "auditar", "verificar", "comparar", "identificar", "resolver"])
            has_numbers = bool(__import__('re').search(r'\d+', thought_text))
            score = round((min(len(thought_text)/200,1.0)*10 + (10.0 if has_action else 3.0) + (10.0 if has_numbers else 5.0))/3, 1)
            new_thought["score"] = score
            summary_lines.append(f"   🤖 Auto-scored: {score}/10")
        except:
            pass  # Never let auto-eval break the main flow

    return {
        "content": [{"type": "text", "text": "\n".join(summary_lines)}],
        "chainId": chain_id,
        "thoughtCount": len(chain["thoughts"]),
    }


def tool_thought_similarity(args: dict) -> dict:
    """Find similar thoughts in a chain."""
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    thought_text = args["thought"]
    top_n = min(args.get("topN", 3), 10)
    min_score = args.get("minScore", 0.1)

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
    thoughts = chain["thoughts"]
    if len(thoughts) < 2:
        return {"content": [{"type": "text", "text": "Not enough thoughts for similarity analysis (need ≥2)"}]}

    vectors, idf = _build_tfidf(thoughts)
    # Build vector for the query thought
    query_tokens = _tokenize(thought_text)
    query_vec = {}
    if query_tokens:
        tf = Counter(query_tokens)
        norm = 0.0
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                query_vec[term] = score
                norm += score * score
        norm = math.sqrt(norm) if norm > 0 else 1.0
        query_vec = {t: s / norm for t, s in query_vec.items()}

    scores = []
    for i, vec in enumerate(vectors):
        sim = _cosine_similarity(query_vec, vec)
        if sim >= min_score:
            t = thoughts[i]
            scores.append((sim, t["number"], t["thought"][:120]))

    scores.sort(reverse=True)
    top = scores[:top_n]

    if not top:
        return {"content": [{"type": "text", "text": "No similar thoughts found above minimum score."}]}

    lines = [f"🔍 Top {len(top)} similar thoughts in chain '{chain_id}':"]
    for sim, num, text in top:
        bar = "█" * int(sim * 10) + "░" * (10 - int(sim * 10))
        lines.append(f"   {bar} {sim:.0%} — #{num}: {text}")

    # Store similarity results for dashboard
    if top:
        session.chains[chain_id].setdefault("similarities", []).append({
            "query": thought_text[:100],
            "top_match_score": top[0][0] if top else 0,
            "top_match_thought": top[0][2][:100] if top else "",
            "recorded_at": time.time(),
        })

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_thought_contradiction(args: dict) -> dict:
    """Detect contradictory thoughts."""
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    thought_text = args["thought"]

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
    thoughts = chain["thoughts"]
    if not thoughts:
        return {"content": [{"type": "text", "text": "No thoughts in chain to check against."}]}

    query_sentiment = _sentiment_heuristic(thought_text)
    vectors, idf = _build_tfidf(thoughts)

    # Build query vector
    query_tokens = _tokenize(thought_text)
    query_vec = {}
    if query_tokens:
        tf = Counter(query_tokens)
        norm = 0.0
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                query_vec[term] = score
                norm += score * score
        norm = math.sqrt(norm) if norm > 0 else 1.0
        query_vec = {t: s / norm for t, s in query_vec.items()}

    contradictions = []
    for i, (vec, t) in enumerate(zip(vectors, thoughts)):
        sim = _cosine_similarity(query_vec, vec)
        t_sentiment = _sentiment_heuristic(t["thought"])

        # Contradiction: similar topic (sim > 0.15) BUT opposite sentiment
        if sim > 0.08 and abs(query_sentiment - t_sentiment) > 0.15:
            sign_q = "positive" if query_sentiment > 0 else "negative"
            sign_t = "positive" if t_sentiment > 0 else "negative"
            contradictions.append({
                "number": t["number"],
                "thought": t["thought"][:150],
                "similarity": round(sim, 2),
                "issue": f"Similar topic but opposite tone ({sign_q} vs {sign_t})"
            })

    if not contradictions:
        return {"content": [{"type": "text", "text": "✅ No contradictions detected in the chain."}]}

    lines = [f"⚠️  Found {len(contradictions)} potential contradiction(s):"]
    for c in contradictions:
        lines.append(f"   #{c['number']}: {c['issue']}")
        lines.append(f"      \"{c['thought'][:100]}...\"")
        lines.append(f"      (similarity: {c['similarity']:.0%})")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_thought_summarize(args: dict) -> dict:
    """Summarize a chain via semantic clustering."""
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    max_clusters = min(args.get("maxClusters", 5), 10)

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
    thoughts = chain["thoughts"]
    if not thoughts:
        return {"content": [{"type": "text", "text": "Chain is empty. Nothing to summarize."}]}

    if len(thoughts) == 1:
        return {"content": [{"type": "text", "text": f"Chain has 1 thought: \"{thoughts[0]['thought'][:200]}\""}]}

    vectors, idf = _build_tfidf(thoughts)

    # Simple agglomerative clustering based on cosine similarity
    n = len(vectors)
    clusters = [[i] for i in range(n)]  # each thought starts alone

    while len(clusters) > max_clusters:
        # Find most similar pair of clusters
        best_sim = -1
        best_pair = (0, 1)
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                # Average linkage similarity
                sims = []
                for ai in clusters[i]:
                    for bj in clusters[j]:
                        sims.append(_cosine_similarity(vectors[ai], vectors[bj]))
                avg_sim = sum(sims) / len(sims) if sims else 0
                if avg_sim > best_sim:
                    best_sim = avg_sim
                    best_pair = (i, j)

        if best_sim < 0.05:
            break

        # Merge
        i, j = best_pair
        clusters[i].extend(clusters[j])
        clusters.pop(j)

    # Generate cluster labels from top TF-IDF terms
    lines = [f"📋 Summary of chain '{chain_id}' — {len(thoughts)} thoughts in {len(clusters)} theme(s):"]
    for ci, cluster in enumerate(clusters, 1):
        # Find top terms for this cluster
        all_terms = Counter()
        for idx in cluster:
            for term, score in vectors[idx].items():
                all_terms[term] += score
        top_terms = [t for t, _ in all_terms.most_common(5)]

        thoughts_in_cluster = [thoughts[i] for i in cluster]
        lines.append(f"\n   🏷️  Theme {ci}: {', '.join(top_terms[:3])}")
        lines.append(f"      {len(thoughts_in_cluster)} thoughts (#{thoughts_in_cluster[0]['number']}–#{thoughts_in_cluster[-1]['number']})")
        for t in thoughts_in_cluster[:3]:
            lines.append(f"         #{t['number']}: {t['thought'][:100]}...")
        if len(thoughts_in_cluster) > 3:
            lines.append(f"         ... and {len(thoughts_in_cluster) - 3} more")

    # Overall stats
    revisions = sum(1 for t in thoughts if t.get("isRevision"))
    branches = sum(1 for t in thoughts if t.get("branchFromThought"))
    lines.append(f"\n   📊 {len(thoughts)} thoughts | {revisions} revisions | {branches} branches | {len(clusters)} themes")

    # Store clusters in chain metadata for dashboard
    cluster_data = []
    for ci, cluster in enumerate(clusters, 1):
        all_terms = Counter()
        for idx in cluster:
            for term, score in vectors[idx].items():
                all_terms[term] += score
        top_terms = [t for t, _ in all_terms.most_common(3)]
        cluster_data.append({
            "theme": ci,
            "label": f"Theme {ci}: {', '.join(top_terms)}",
            "count": len(cluster),
            "preview": thoughts[cluster[0]]["thought"][:120] if cluster else "",
        })
    session.chains[chain_id]["clusters"] = cluster_data

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_thought_to_plan(args: dict) -> dict:
    """Convert chain to actionable plan."""
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    fmt = args.get("format", "markdown")

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
    thoughts = chain["thoughts"]

    # Filter out revisions, keep only final thoughts
    revised = {t["revisesThought"] for t in thoughts if t.get("revisesThought")}
    active = [t for t in thoughts if t["number"] not in revised and not t.get("isRevision")]

    if not active:
        return {"content": [{"type": "text", "text": "No actionable thoughts after filtering revisions."}]}

    if fmt == "json":
        plan = {
            "chainId": chain_id,
            "totalSteps": len(active),
            "steps": [{"step": i + 1, "number": t["number"], "action": t["thought"]} for i, t in enumerate(active)]
        }
        result_text = json.dumps(plan, indent=2, ensure_ascii=False)
    else:
        lines = [f"# 📋 Action Plan — Chain '{chain_id}'", ""]
        lines.append(f"**{len(active)} steps** extracted from {len(thoughts)} thoughts")
        lines.append("")
        for i, t in enumerate(active, 1):
            lines.append(f"## Step {i}")
            lines.append(f"**Origin**: Thought #{t['number']}")
            lines.append(f"**Action**: {t['thought']}")
            if i > 1:
                lines.append(f"**Depends on**: Step {i - 1}")
            lines.append("")
        result_text = "\n".join(lines)
    
    # Store plan in chain metadata for dashboard
    session.chains[chain_id]["plan"] = {
        "steps": len(active),
        "format": fmt,
        "preview": active[0]["thought"][:150] if active else "",
        "created_at": time.time(),
    }
    
    return {"content": [{"type": "text", "text": result_text}]}


def tool_thought_evaluate(args: dict) -> dict:
    """Evaluate thought quality."""
    session = _get_session(args.get("session_id"))  # multi-agent
    chain_id = args["chainId"]
    thought_number = args["thoughtNumber"]

    if chain_id not in session.chains:
        return {"content": [{"type": "text", "text": f"Error: Chain '{chain_id}' not found"}]}

    chain = session.chains[chain_id]
    target = None
    for t in chain["thoughts"]:
        if t["number"] == thought_number:
            target = t
            break

    if not target:
        return {"content": [{"type": "text", "text": f"Error: Thought #{thought_number} not found in chain '{chain_id}'"}]}

    thought_text = target["thought"]

    # Heuristic evaluation
    specificity = min(len(thought_text) / 200, 1.0)  # longer = more specific
    has_numbers = bool(re.search(r'\d+', thought_text))
    has_action = any(w in thought_text.lower() for w in
                     ["hacer", "crear", "ejecutar", "analizar", "implementar",
                      "migrar", "configurar", "build", "deploy", "run", "test",
                      "create", "execute", "analyze"])

    scores = {
        "specificity": round(specificity * 10, 1),
        "actionability": 10.0 if has_action else 3.0,
        "concreteness": 10.0 if has_numbers else 5.0,
    }
    overall = round(sum(scores.values()) / len(scores), 1)

    feedback = []
    if specificity < 0.3:
        feedback.append("💡 Be more specific — add details, numbers, or concrete steps")
    if not has_action:
        feedback.append("💡 Add an action verb to make this thought actionable")
    if not has_numbers:
        feedback.append("💡 Include numbers (time estimates, counts, versions)")
    if overall >= 8:
        feedback.append("✅ Excellent thought — specific, actionable, and concrete")

    lines = [
        f"📊 Evaluation of Thought #{thought_number} in chain '{chain_id}'",
        f"   Overall: {'⭐' * int(overall / 2)} {overall}/10",
        f"   Specificity:   {scores['specificity']}/10",
        f"   Actionability: {scores['actionability']}/10",
        f"   Concreteness:  {scores['concreteness']}/10",
        "",
    ] + feedback

    # Store score on thought object for dashboard stats
    target["score"] = overall

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_thought_bridge(args: dict) -> dict:
    """Cross-chain thought connections."""
    session = _get_session(args.get("session_id"))  # multi-agent
    thought_text = args.get("thought", "")
    top_n = min(args.get("topN", 3), 5)

    if not thought_text:
        return {"content": [{"type": "text", "text": "No thought provided for bridging. Pass 'thought' parameter."}]}

    if len(session.chains) < 2:
        return {"content": [{"type": "text", "text": "Need at least 2 chains for cross-chain bridging."}]}

    # Build query vector
    query_tokens = _tokenize(thought_text)
    if not query_tokens:
        return {"content": [{"type": "text", "text": "No meaningful tokens in thought to bridge."}]}

    connections = []
    for cid, chain in session.chains.items():
        thoughts = chain["thoughts"]
        if not thoughts:
            continue

        vectors, idf = _build_tfidf(thoughts)
        query_vec = {}
        norm = 0.0
        tf = Counter(query_tokens)
        for term, count in tf.items():
            if term in idf:
                score = count * idf[term]
                query_vec[term] = score
                norm += score * score
        norm = math.sqrt(norm) if norm > 0 else 1.0
        query_vec = {t: s / norm for t, s in query_vec.items()}

        best_sim = 0
        best_thought = None
        for i, vec in enumerate(vectors):
            sim = _cosine_similarity(query_vec, vec)
            if sim > best_sim:
                best_sim = sim
                best_thought = thoughts[i]

        if best_sim > 0.1 and best_thought:
            connections.append((cid, best_sim, best_thought))

    connections.sort(key=lambda x: x[1], reverse=True)
    top = connections[:top_n]

    if not top:
        return {"content": [{"type": "text", "text": "No cross-chain connections found. Try a more specific thought."}]}

    lines = [f"🌉 Cross-chain bridges for: \"{thought_text[:80]}...\""]
    for cid, sim, t in top:
        bar = "█" * int(sim * 10) + "░" * (10 - int(sim * 10))
        lines.append(f"   {bar} {sim:.0%} — Chain '{cid}', #{t['number']}: {t['thought'][:100]}...")

    # Store bridges in session for dashboard
    for cid, sim, t in top:
        session.bridges.append({
            "query": thought_text[:80],
            "chain_id": cid,
            "score": round(sim, 2),
            "thought_preview": t["thought"][:100],
            "recorded_at": time.time(),
        })

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Assumption Tracker — cognitive safety tools
# ═══════════════════════════════════════════════════════════════════════

_assumptions: list[dict] = []
_next_assumption_id = 1


def tool_assume(args: dict) -> dict:
    """Record an assumption explicitly."""
    session = _get_session(args.get("session_id"))  # multi-agent
    global _next_assumption_id

    statement = args["statement"]
    category = args.get("category", "other")
    confidence_note = args.get("confidence_note", "")

    assumption = {
        "id": _next_assumption_id,
        "statement": statement,
        "category": category,
        "confidence_note": confidence_note,
        "status": "unverified",
        "timestamp": time.time(),
    }
    session.assumptions.append(assumption)
    _next_assumption_id += 1

    lines = [
        f"📝 Assumption #{assumption['id']} recorded:",
        f"   \"{statement}\"",
        f"   Category: {category}",
    ]
    if confidence_note:
        lines.append(f"   Basis: {confidence_note}")
    lines.append(f"   Status: ⏳ unverified — check later with check_assumption")

    # Show related unverified assumptions for awareness
    unverified = [a for a in session.assumptions if a["status"] == "unverified" and a["id"] != assumption["id"]]
    if unverified:
        lines.append(f"\n   ⚠️  You have {len(unverified)} other unverified assumption(s):")
        for a in unverified[-3:]:
            lines.append(f"      #{a['id']}: {a['statement'][:80]}...")
        if len(unverified) > 3:
            lines.append(f"      ... and {len(unverified)-3} more. Use list_assumptions() to see all.")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_list_assumptions(args: dict) -> dict:
    """List assumptions with optional filtering."""
    session = _get_session(args.get("session_id"))  # multi-agent
    status_filter = args.get("status", "unverified")
    category_filter = args.get("category")

    filtered = session.assumptions
    if status_filter != "all":
        filtered = [a for a in filtered if a["status"] == status_filter]
    if category_filter:
        filtered = [a for a in filtered if a["category"] == category_filter]

    if not filtered:
        return {"content": [{"type": "text", "text": f"No assumptions found (filter: status={status_filter}, category={category_filter or 'any'})."}]}

    total = len(session.assumptions)
    confirmed = sum(1 for a in session.assumptions if a["status"] == "confirmed")
    refuted = sum(1 for a in session.assumptions if a["status"] == "refuted")
    unverified_count = total - confirmed - refuted

    lines = [f"📋 Assumptions ({len(filtered)} shown, {total} total)"]
    lines.append(f"   ✅ {confirmed} confirmed | ❌ {refuted} refuted | ⏳ {unverified_count} unverified")
    lines.append("")

    for a in filtered:
        icon = {"unverified": "⏳", "confirmed": "✅", "refuted": "❌"}.get(a["status"], "?")
        lines.append(f"   {icon} #{a['id']} [{a['category']}] {a['statement'][:120]}")
        if a.get("evidence"):
            lines.append(f"      Evidence: {a['evidence'][:100]}")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_check_assumption(args: dict) -> dict:
    """Mark an assumption as confirmed or refuted."""
    session = _get_session(args.get("session_id"))  # multi-agent
    aid = int(args["assumption_id"])
    outcome = args["outcome"]
    evidence = args.get("evidence", "")

    target = None
    for a in session.assumptions:
        if a["id"] == aid:
            target = a
            break

    if not target:
        return {"content": [{"type": "text", "text": f"Error: Assumption #{aid} not found."}]}

    target["status"] = outcome
    target["evidence"] = evidence
    target["checked_at"] = time.time()

    icon = "✅" if outcome == "confirmed" else "❌"
    lines = [f"{icon} Assumption #{aid} → {outcome}"]
    lines.append(f"   \"{target['statement'][:120]}\"")
    if evidence:
        lines.append(f"   Evidence: {evidence[:200]}")

    # Show learning: how many right/wrong so far
    confirmed = sum(1 for a in session.assumptions if a["status"] == "confirmed")
    refuted = sum(1 for a in session.assumptions if a["status"] == "refuted")
    total_checked = confirmed + refuted
    if total_checked > 0:
        pct = confirmed * 100 // total_checked
        lines.append(f"\n   📊 Track record: {confirmed}/{total_checked} confirmed ({pct}%)")
        if pct < 50:
            lines.append(f"   💡 Your assumptions are often wrong — consider listing them before acting.")
        elif pct > 80:
            lines.append(f"   💡 Your assumptions are usually right — but don't get overconfident.")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Mental Model Builder — project knowledge graph
# ═══════════════════════════════════════════════════════════════════════

_model: dict[str, dict] = {}  # path → {role, deps, dependents, notes, added_at}


def _update_dependents(session: Session):
    """Recalculate reverse dependencies (who depends on whom)."""
    for path in session.model:
        session.model[path]["dependents"] = []
    for path, node in session.model.items():
        for dep in node.get("deps", []):
            if dep in session.model:
                session.model[dep]["dependents"].append(path)


def tool_model_add(args: dict) -> dict:
    """Add an entity to the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    # Accept both "entity" (new API) and "path" (legacy)
    entity = args.get("entity") or args.get("path", "")
    if not entity:
        return {"content": [{"type": "text", "text": "Error: 'entity' or 'path' parameter required."}]}
    # Normalize to forward slashes for cross-platform consistency
    entity = entity.replace("\\", "/")
    role = args.get("role", "other")
    deps = args.get("deps", [])
    notes = args.get("notes", "")
    properties = args.get("properties", {})

    existing = entity in session.model

    session.model[entity] = {
        "role": role,
        "deps": list(deps),
        "dependents": [],
        "notes": notes,
        "properties": dict(properties) if isinstance(properties, dict) else {},
        "added_at": time.time(),
    }
    _update_dependents(session)

    action = "Updated" if existing else "Added"
    lines = [f"🧠 {action} to model: {entity}"]
    if role != "other":
        lines.append(f"   Role: {role}")
    if deps:
        lines.append(f"   Dependencies: {', '.join(deps[:5])}")
    if notes:
        lines.append(f"   Notes: {notes[:120]}")

    # Show connected files
    connected = set(deps)
    for p, node in session.model.items():
        if path in node.get("deps", []) and p != path:
            connected.add(p)
    if connected:
        lines.append(f"   🔗 Connected: {len(connected)} file(s)")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_model_query(args: dict) -> dict:
    """Query the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    query = args["query"].strip()
    target = args.get("target", "")

    if not session.model:
        return {"content": [{"type": "text", "text": "Model is empty. Use model_add to populate it first."}]}

    lines = []

    # "deps of path"
    if query.startswith("deps of ") or query.startswith("deps "):
        path = target or query.replace("deps of ", "").replace("deps ", "").strip()
        if path in session.model:
            deps = session.model[path].get("deps", [])
            lines.append(f"📦 Dependencies of {path} ({session.model[path].get('role','?')}):")
            for d in deps:
                role_str = f" [{session.model[d]['role']}]" if d in session.model else " [unknown]"
                lines.append(f"   → {d}{role_str}")
            if not deps:
                lines.append("   (no dependencies)")
        else:
            lines.append(f"❌ '{path}' not in model. Add it with model_add first.")

    # "dependents of path" / "who depends on path"
    elif "dependent" in query or "who depends" in query:
        path = target or query.split("of ")[-1].strip()
        if path in session.model:
            deps_of = session.model[path].get("dependents", [])
            lines.append(f"📦 Files that depend on {path}:")
            for d in deps_of:
                lines.append(f"   ← {d} [{session.model[d].get('role','?')}]")
            if not deps_of:
                lines.append(f"   ✅ No files depend on {path} — safe to change!")
        else:
            lines.append(f"❌ '{path}' not in model.")

    # "role=X"
    elif query.startswith("role="):
        role = query.replace("role=", "").strip()
        matches = [p for p, n in session.model.items() if n.get("role") == role]
        lines.append(f"📦 Files with role '{role}' ({len(matches)}):")
        for m in sorted(matches):
            lines.append(f"   {m}" + (f" — {session.model[m].get('notes','')[:60]}" if session.model[m].get('notes') else ""))

    # "impact of path"
    elif "impact" in query:
        path = target or query.split("of ")[-1].strip()
        if path in session.model:
            deps_of = session.model[path].get("dependents", [])
            lines.append(f"💥 Impact of changing {path}:")
            if deps_of:
                lines.append(f"   {len(deps_of)} file(s) would be affected:")
                for d in deps_of:
                    lines.append(f"   ⚠️  {d} [{session.model[d].get('role','?')}]")
            else:
                lines.append(f"   ✅ No impact — safe to change!")
        else:
            lines.append(f"❌ '{path}' not in model.")

    # "all"
    elif query == "all":
        lines.append(f"📦 Full model ({len(session.model)} files):")
        for path in sorted(_model):
            n = session.model[path]
            lines.append(f"   {path} [{n.get('role','?')}] → {len(n.get('deps',[]))} deps, {len(n.get('dependents',[]))} users")

    else:
        lines.append(f"❓ Unknown query: '{query}'")
        lines.append("Try: 'deps of <path>', 'dependents of <path>', 'role=<name>', 'impact of <path>', 'all'")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_model_stats(args: dict) -> dict:
    """Model statistics."""
    session = _get_session(args.get("session_id"))  # multi-agent
    if not session.model:
        return {"content": [{"type": "text", "text": "Model is empty."}]}

    roles = Counter(n.get("role", "other") for n in session.model.values())
    total_deps = sum(len(n.get("deps", [])) for n in session.model.values())
    total_files = len(session.model)
    avg_deps = total_deps / total_files if total_files else 0

    # Most connected files
    connections = [(p, len(n.get("deps", [])) + len(n.get("dependents", []))) for p, n in session.model.items()]
    connections.sort(key=lambda x: -x[1])

    lines = [
        f"📊 Mental Model Stats:",
        f"   Files mapped:   {total_files}",
        f"   Dependencies:   {total_deps} (avg {avg_deps:.1f}/file)",
        f"",
        f"   Roles:",
    ]
    for role, count in roles.most_common():
        bar = "█" * min(count, 30)
        lines.append(f"   {role:<20} {bar} {count}")

    lines.append(f"\n   Most connected files:")
    for path, conn in connections[:5]:
        n = session.model[path]
        lines.append(f"   {path} [{n.get('role','?')}] — {conn} connections")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_model_map(args: dict) -> dict:
    """Visual tree map of the model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    if not session.model:
        return {"content": [{"type": "text", "text": "Model is empty."}]}

    root = args.get("root_path", ".")
    max_depth = args.get("max_depth", 3)

    # Build tree from paths
    lines = [f"🗺️  Project Map:"]

    # Find entry points (files with no incoming deps from the model)
    has_dependents = set()
    for n in session.model.values():
        for d in n.get("dependents", []):
            has_dependents.add(d)

    # Entry points: files with dependents but no deps within model, OR files with deps but no dependents
    entries = sorted(session.model.keys())

    # Group by directory
    dirs: dict[str, list] = {}
    for path in entries:
        d = os.path.dirname(path) or "."
        if d not in dirs:
            dirs[d] = []
        dirs[d].append(path)

    for directory in sorted(dirs):
        lines.append(f"\n📁 {directory}/")
        for path in sorted(dirs[directory]):
            n = session.model[path]
            fname = os.path.basename(path)
            role_icon = {"authentication":"🔐","database":"🗄️","config":"⚙️","api":"🔌","model":"📊","test":"🧪","util":"🔧","entry_point":"🚀"}.get(n.get("role",""),"📄")
            deps_str = f" → {', '.join(n.get('deps',[])[:3])}" if n.get("deps") else ""
            lines.append(f"   {role_icon} {fname} [{n.get('role','?')}]{deps_str}")

    lines.append(f"\n📊 {len(session.model)} files mapped across {len(dirs)} directories")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_model_remove(args: dict) -> dict:
    """Remove a file from the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    path = args["path"]

    if path not in _model:
        return {"content": [{"type": "text", "text": f"'{path}' is not in the model."}]}

    # Find what depends on this file
    affected = session.model[path].get("dependents", [])
    role = session.model[path].get("role", "?")

    del session.model[path]
    _update_dependents(session)

    lines = [f"🗑️  Removed from model: {path} [{role}]"]
    if affected:
        lines.append(f"   ⚠️  {len(affected)} file(s) had this as dependency:")
        for a in affected:
            lines.append(f"      {a} — check if still valid")
    lines.append(f"   Model now has {len(session.model)} file(s)")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_model_scan(args: dict) -> dict:
    """Auto-scan a directory and build the mental model."""
    session = _get_session(args.get("session_id"))  # multi-agent
    scan_path = args.get("path", ".")
    patterns = args.get("file_patterns", ["*.py", "*.js", "*.ts"])
    max_files = min(args.get("max_files", 50), 200)
    max_depth = args.get("max_depth", 1)  # 1 = non-recursive, 0 = unlimited
    detect_deps_flag = args.get("detect_deps", False)

    scan_dir = Path(scan_path)
    if not scan_dir.exists() or not scan_dir.is_dir():
        return {"content": [{"type": "text", "text": f"Error: Directory not found: {scan_path}"}]}

    # Use os.walk for depth control (faster than rglob on huge dirs)
    discovered = []
    for root, dirs, files in os.walk(scan_path):
        # Skip hidden dirs and common excludes
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ("node_modules", "__pycache__", ".git", "venv", "dist", "build", ".hermes")]
        
        # Check depth
        if max_depth > 0:
            depth = root[len(str(scan_path)):].count(os.sep)
            if depth >= max_depth:
                dirs[:] = []  # Don't go deeper
        
        for fname in files:
            fpath = Path(root) / fname
            if any(fpath.match(p) for p in patterns):
                discovered.append(fpath)
                if len(discovered) >= max_files:
                    break
        if len(discovered) >= max_files:
            break

    discovered = discovered[:max_files]

    # Guess role from filename and path
    def guess_role(filepath: Path) -> str:
        name = filepath.stem.lower()
        path_str = str(filepath).lower()
        if "test" in name or "spec" in name:
            return "test"
        if "auth" in name or "login" in name or "session" in name:
            return "authentication"
        if "db" in name or "database" in name or "model" in name or "schema" in name:
            return "database"
        if "api" in name or "route" in name or "endpoint" in name or "handler" in name:
            return "api"
        if "config" in name or "setting" in name or ".env" in name:
            return "config"
        if "main" in name or "index" in name or "app" in name or "server" in name:
            return "entry_point"
        if "util" in name or "helper" in name or "common" in name:
            return "util"
        if name.startswith("test_"):
            return "test"
        return "other"

    # Detect import dependencies for Python files (only if requested)
    def detect_deps(filepath: Path) -> list:
        if not detect_deps_flag or filepath.suffix != ".py":
            return []
        deps = []
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except:
            return deps
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("from ") or line.startswith("import "):
                parts = line.replace("from ", "").replace("import ", "").split()
                if parts:
                    mod = parts[0]
                    mod_path = mod.replace(".", os.sep) + ".py"
                    for d in discovered:
                        if str(d).endswith(mod_path) or d.stem == mod.split(".")[-1]:
                            rel = str(d.relative_to(scan_dir)) if d.is_relative_to(scan_dir) else str(d)
                            deps.append(rel)
                            break
        return deps[:10]

    # Build model
    added = 0
    updated = 0
    for f in discovered:
        try:
            rel = str(f.relative_to(scan_dir))
        except ValueError:
            rel = str(f)
        # Normalize to forward slashes for cross-platform query consistency
        rel = rel.replace("\\", "/")
        role = guess_role(f)
        deps = detect_deps(f)

        existing = rel in _model
        session.model[rel] = {
            "role": role,
            "deps": deps,
            "dependents": [],
            "notes": f"Auto-scanned from {scan_path}",
            "added_at": time.time(),
        }
        if existing:
            updated += 1
        else:
            added += 1

    _update_dependents(session)

    lines = [
        f"🔍 Scanned {scan_path}",
        f"   Files found:    {len(discovered)}",
        f"   Added to model: {added}",
        f"   Updated:        {updated}",
        f"   Total in model: {len(session.model)}",
        f"",
        f"   Use model_map() to visualize or model_query() to explore.",
    ]
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Context Decay Detector — preserve critical info from context loss
# ═══════════════════════════════════════════════════════════════════════

_preserved: list[dict] = []


def tool_context_preserve(args: dict) -> dict:
    """Mark information as worth preserving."""
    content = args.get("content", "")
    if not content:
        return {"content": [{"type": "text", "text": "Error: 'content' parameter required."}]}
    label = args.get("label", "")
    priority = args.get("priority", "high")
    category = args.get("category", "other")

    item = {
        "label": label,
        "content": content,
        "priority": priority,
        "category": category,
        "timestamp": time.time(),
    }
    _preserved.append(item)

    priority_icon = {"critical": "🔴", "high": "🟡", "medium": "🟢"}.get(priority, "⚪")
    label_str = f" [{label}]" if label else ""
    lines = [
        f"{priority_icon} Preserved{label_str} [{priority}] [{category}]:",
        f"   \"{content[:200]}\"",
    ]

    # Warn if list is growing
    critical_count = sum(1 for p in _preserved if p["priority"] == "critical")
    total = len(_preserved)
    lines.append(f"   📊 Preservation list: {total} items ({critical_count} critical)")

    if total > 15:
        lines.append(f"   ⚠️  List is large ({total} items). Consider using thought_summarize to condense.")
    if total > 30:
        lines.append(f"   🚨 List is very large ({total} items). High risk of losing information.")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_context_check(args: dict) -> dict:
    """Check preserved items and decay risk."""
    max_items = args.get("max_items", 20)

    if not _preserved:
        return {"content": [{"type": "text", "text": "📋 No items preserved yet. Use context_preserve to mark critical information."}]}

    total = len(_preserved)
    by_priority = {"critical": 0, "high": 0, "medium": 0}
    by_category = {}
    for p in _preserved:
        by_priority[p["priority"]] = by_priority.get(p["priority"], 0) + 1
        cat = p["category"]
        by_category[cat] = by_category.get(cat, 0) + 1

    lines = [f"📋 Context Preservation Check — {total} items"]
    lines.append(f"   🔴 {by_priority.get('critical',0)} critical | 🟡 {by_priority.get('high',0)} high | 🟢 {by_priority.get('medium',0)} medium")
    lines.append("")

    # Risk assessment
    if total > 20:
        lines.append(f"   🚨 HIGH DECAY RISK: {total} items preserved.")
        lines.append(f"   💡 Actions: (1) use thought_summarize to condense,")
        lines.append(f"        (2) move non-critical items to memory,")
        lines.append(f"        (3) prioritize critical items only.")
    elif total > 10:
        lines.append(f"   ⚠️  MEDIUM DECAY RISK: {total} items. Monitor closely.")
    else:
        lines.append(f"   ✅ LOW DECAY RISK: {total} items. Context should be stable.")

    # Show by category
    lines.append(f"\n   By category:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        lines.append(f"   {cat:<15} {'█' * min(count, 20)} {count}")

    # Show most recent critical/high
    lines.append(f"\n   Recent critical/high items:")
    shown = 0
    for p in reversed(_preserved):
        if p["priority"] in ("critical", "high") and shown < max_items:
            icon = {"critical": "🔴", "high": "🟡"}.get(p["priority"], "⚪")
            label_str = f" [{p['label']}]" if p.get("label") else ""
            lines.append(f"   {icon}{label_str} [{p['category']}] {p['content'][:120]}...")
            shown += 1
        if shown >= 10:
            break

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Work Tracker — persistent work log across sessions
# ═══════════════════════════════════════════════════════════════════════

_works: list[dict] = []
_next_work_id = 1
WORK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".work_log.json")

def _load_works():
    """Load persisted work log from disk."""
    global _next_work_id
    session = _get_session()
    try:
        if os.path.exists(WORK_FILE):
            with open(WORK_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                session.works = data.get("works", [])
                _next_work_id = data.get("next_id", 1)
    except Exception:
        pass

def _save_works():
    """Persist work log to disk."""
    session = _get_session()
    try:
        os.makedirs(os.path.dirname(WORK_FILE), exist_ok=True)
        with open(WORK_FILE, 'w', encoding='utf-8') as f:
            json.dump({"works": session.works, "next_id": _next_work_id}, f, indent=2)
    except Exception:
        pass

_load_works()


def tool_work_start(args: dict) -> dict:
    """Start tracking a work item."""
    global _next_work_id
    session = _get_session(args.get("session_id"))

    item = args["item"]
    category = args.get("category", "other")

    work = {
        "id": _next_work_id,
        "item": item,
        "category": category,
        "status": "in_progress",
        "started_at": time.time(),
        "blocked_at": None,
        "blocked_reason": "",
        "done_at": None,
        "result": "",
    }
    session.works.append(work)
    _next_work_id += 1
    _save_works()

    in_progress = sum(1 for w in session.works if w["status"] == "in_progress")
    lines = [
        f"🔧 Work #{work['id']} started: {item}",
        f"   Category: {category}",
        f"   You have {in_progress} active work item(s)",
    ]
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_work_block(args: dict) -> dict:
    """Mark a work item as blocked."""
    session = _get_session(args.get("session_id"))
    wid = args["work_id"]
    reason = args["reason"]

    for w in session.works:
        if w["id"] == wid:
            w["status"] = "blocked"
            w["blocked_at"] = time.time()
            w["blocked_reason"] = reason
            _save_works()
            return {"content": [{"type": "text", "text": f"🚫 Work #{wid} blocked: {reason}"}]}

    return {"content": [{"type": "text", "text": f"Error: Work #{wid} not found."}]}


def tool_work_done(args: dict) -> dict:
    """Mark a work item as done."""
    session = _get_session(args.get("session_id"))
    wid = args["work_id"]
    result = args.get("result", "")

    for w in session.works:
        if w["id"] == wid:
            w["status"] = "done"
            w["done_at"] = time.time()
            w["result"] = result
            _save_works()
            lines = [f"✅ Work #{wid} completed: {w['item']}"]
            if result:
                lines.append(f"   Result: {result}")
            return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}

    return {"content": [{"type": "text", "text": f"Error: Work #{wid} not found."}]}


def tool_work_log(args: dict) -> dict:
    """Show work log."""
    session = _get_session(args.get("session_id"))
    status_filter = args.get("status", "all")
    limit = args.get("limit", 20)

    filtered = session.works
    if status_filter != "all":
        filtered = [w for w in filtered if w["status"] == status_filter]
    filtered = filtered[-limit:]

    if not filtered:
        return {"content": [{"type": "text", "text": "No work items found. Use work_start to begin tracking."}]}

    in_progress = sum(1 for w in session.works if w["status"] == "in_progress")
    blocked = sum(1 for w in session.works if w["status"] == "blocked")
    done = sum(1 for w in session.works if w["status"] == "done")

    lines = [f"📋 Work Log ({len(filtered)} shown, {len(session.works)} total)"]
    lines.append(f"   🔧 {in_progress} in progress | 🚫 {blocked} blocked | ✅ {done} done")
    lines.append("")

    icons = {"in_progress": "🔧", "blocked": "🚫", "done": "✅"}
    for w in filtered:
        icon = icons.get(w["status"], "?")
        lines.append(f"   {icon} #{w['id']} [{w['category']}] {w['item'][:100]}")
        if w["status"] == "blocked" and w.get("blocked_reason"):
            lines.append(f"      Blocked: {w['blocked_reason'][:80]}")
        if w["status"] == "done" and w.get("result"):
            lines.append(f"      Result: {w['result'][:80]}")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Context Estimator — heuristic context usage assessment
# ═══════════════════════════════════════════════════════════════════════

_session_start = time.time()
_tool_calls = 0
_estimated_chars = 0


def tool_context_estimate(args: dict) -> dict:
    """Estimate context usage."""
    session = _get_session(args.get("session_id"))
    uptime = time.time() - _session_start
    tool_estimate = _tool_calls * 500
    content_estimate = _estimated_chars // 4
    total_est = tool_estimate + content_estimate
    context_limit = 80_000
    pct = min(100, (total_est * 100) // context_limit)
    if pct > 70:
        risk = "HIGH"; suggestion = "Consider externalizing key thoughts to sequential_thinking and summarizing with thought_summarize."
    elif pct > 40:
        risk = "MEDIUM"; suggestion = "Monitor. Use context_preserve for critical findings."
    else:
        risk = "LOW"; suggestion = "Context is healthy. No action needed."
    lines = [
        f"📊 Context Estimate: ~{pct}% used (risk: {risk})",
        f"   Session: {uptime:.0f}s | Tool calls: {_tool_calls} | Est. tokens: ~{total_est:,}",
        f"   Model limit: ~{context_limit:,} tokens",
        f"", f"   💡 {suggestion}",
    ]
    if risk == "HIGH":
        lines += ["   ⚡ Actions:", "      • Use sequential_thinking to offload reasoning",
                   "      • Use context_preserve for must-keep information",
                   "      • Use thought_summarize to condense chains",
                   "      • Avoid large read_files — use search_with_context instead"]
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Session Management Tools
# ═══════════════════════════════════════════════════════════════════════

def tool_session_init(args: dict) -> dict:
    """Create or retrieve a multi-agent session."""
    global _next_session_num
    label = args.get("label", "")
    sid = args.get("session_id")

    if sid and sid in _sessions:
        session = _sessions[sid]
        action = "resumed"
    else:
        if not sid:
            sid = f"session_{_next_session_num}"
            _next_session_num += 1
        _sessions[sid] = Session(label=label or sid)
        session = _sessions[sid]
        action = "created"

    return {"content": [{"type": "text", "text": (
        f"🟢 Session {action}: {sid}\n"
        f"   Label: {session.label}\n"
        f"   Chains: {len(session.chains)}\n"
        f"   Assumptions: {len(session.assumptions)}\n"
        f"   Model files: {len(session.model)}\n"
        f"   Works: {len(session.works)}\n"
        f"   Use session_id='{sid}' in subsequent tool calls to keep state isolated."
    )}]}

def tool_session_list(args: dict) -> dict:
    """List all active sessions."""
    if not _sessions:
        return {"content": [{"type": "text", "text": "No active sessions. Use session_init to create one."}]}

    lines = ["📋 Active Sessions:"]
    # Build collision map from file touches
    from collections import defaultdict
    now = time.time()
    window = 300  # 5 minute window
    by_file = defaultdict(set)
    for t in _file_touches:
        if now - t.get("timestamp", 0) < window:
            by_file[t.get("path", "")].add(t.get("session_id", ""))
    collisions = {f: sids for f, sids in by_file.items() if len(sids) > 1}
    for sid, s in sorted(_sessions.items()):
        age = time.time() - s.updated_at
        line = (
            f"   {sid}: {s.label or '(no label)'} | "
            f"{len(s.chains)} chains, {len(s.assumptions)} asmp, "
            f"{len(s.model)} model, {s.tool_calls} calls | "
            f"idle {age:.0f}s"
        )
        # Check if this session has collisions
        for fpath, sids in collisions.items():
            if sid in sids:
                others = sids - {sid}
                line += f" | ⚠️ touching {fpath.split('/')[-1]} with {', '.join(others)}"
                break
        lines.append(line)
    if collisions:
        lines.append(f"\n   ⚡ {len(collisions)} file(s) with multi-session activity — check /collisions for details")
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}
    uptime = time.time() - _session_start
    tool_estimate = _tool_calls * 500  # Rough: 500 tokens per tool call
    content_estimate = _estimated_chars // 4  # Rough: 4 chars per token

    total_est = tool_estimate + content_estimate
    # Most models have ~128K context. Hermes typically uses ~60-80K with system prompt.
    context_limit = 80_000
    pct = min(100, (total_est * 100) // context_limit)

    # Risk level
    if pct > 70:
        risk = "HIGH"
        suggestion = "Consider externalizing key thoughts to sequential_thinking and summarizing with thought_summarize."
    elif pct > 40:
        risk = "MEDIUM"
        suggestion = "Monitor. Use context_preserve for critical findings."
    else:
        risk = "LOW"
        suggestion = "Context is healthy. No action needed."

    lines = [
        f"📊 Context Estimate: ~{pct}% used (risk: {risk})",
        f"   Session: {uptime:.0f}s | Tool calls: {_tool_calls} | Est. tokens: ~{total_est:,}",
        f"   Model limit: ~{context_limit:,} tokens",
        f"",
        f"   💡 {suggestion}",
    ]

    # Additional suggestions based on risk
    if risk == "HIGH":
        lines.append(f"   ⚡ Actions:")
        lines.append(f"      • Use sequential_thinking to offload reasoning")
        lines.append(f"      • Use context_preserve for must-keep information")
        lines.append(f"      • Use thought_summarize to condense chains")
        lines.append(f"      • Avoid large read_files — use search_with_context instead")

    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Cross-Session Communication — agent-to-agent messaging
# ═══════════════════════════════════════════════════════════════════════

def tool_agent_message(args: dict) -> dict:
    """Send a message to another agent session."""
    session = _get_session(args.get("session_id"))
    to_session = args.get("to_session", args.get("to", ""))
    content = args.get("content", args.get("message", ""))
    priority = args.get("priority", "normal")
    if not to_session or not content:
        return {"content": [{"type": "text", "text": "Error: 'to_session' and 'content' required."}]}
    # Resolve target: if to_session matches a session ID, use its label
    target_label = to_session
    if to_session in _sessions:
        target_label = _sessions[to_session].label or to_session
    msg = {
        "from_session": session.label or "default",
        "to_session": to_session,
        "content": content,
        "priority": priority,
        "timestamp": time.time(),
    }
    _agent_messages.append(msg)
    if len(_agent_messages) > 200:
        _agent_messages[:] = _agent_messages[-200:]
    _save_state()
    return {"content": [{"type": "text", "text": f"📨 Message sent to '{to_session}' ({priority} priority)."}]}


def tool_agent_inbox(args: dict) -> dict:
    """Read messages sent to this agent session."""
    session = _get_session(args.get("session_id"))
    sid = session.label or "default"
    limit = min(args.get("limit", 20), 50)
    unread_only = args.get("unread_only", False)

    # Match by session label, session_id, or wildcard
    session_id = None
    for sid, s in _sessions.items():
        if s.label == session.label:
            session_id = sid
            break
    msgs = [m for m in _agent_messages if m["to_session"] in (session.label, session_id, "*")]
    if unread_only:
        msgs = [m for m in msgs if not m.get("read")]
    msgs = msgs[-limit:]

    if not msgs:
        return {"content": [{"type": "text", "text": "📭 Inbox empty."}]}

    lines = [f"📬 Inbox ({len(msgs)} messages):"]
    for m in msgs:
        ago = int(time.time() - m["timestamp"])
        ago_str = f"{ago}s ago" if ago < 60 else f"{ago//60}m ago" if ago < 3600 else f"{ago//3600}h ago"
        lines.append(f"   📨 [{ago_str}] {m['from_session']}: {m['content'][:200]}")
        m["read"] = True  # mark as read
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


def tool_collision_check(args: dict) -> dict:
    """Check for file collisions between sessions in the last 5 minutes."""
    from collections import defaultdict
    now = time.time()
    window = args.get("window_seconds", 300)
    by_file = defaultdict(set)
    for t in _file_touches:
        if now - t.get("timestamp", 0) < window:
            by_file[t.get("path", "")].add(t.get("session_id", ""))
    collisions = [(f, sids) for f, sids in by_file.items() if len(sids) > 1]
    if not collisions:
        return {"content": [{"type": "text", "text": "✅ No file collisions detected in the last 5 minutes."}]}
    lines = [f"⚠️  {len(collisions)} file(s) being touched by multiple sessions:"]
    for fpath, sids in collisions:
        fname = fpath.split("/")[-1] if "/" in fpath else fpath
        lines.append(f"   🔴 {fname}: {', '.join(sids)}")
    lines.append(f"\n💡 Use agent_message to coordinate with the other session(s).")
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Pattern Memory — institutional knowledge across sessions
# ═══════════════════════════════════════════════════════════════════════

def tool_pattern_record(args: dict) -> dict:
    """Record a bug pattern or fix strategy."""
    session = _get_session(args.get("session_id"))
    pid = session.next_pattern_id
    session.next_pattern_id += 1
    category = args.get("category", "bug")
    if category not in ("bug", "security", "performance", "design", "testing", "other"):
        category = "other"
    pattern = {
        "id": pid, "pattern_name": args["pattern_name"],
        "description": args["description"],
        "code_snippet": args.get("code_snippet", ""),
        "fix_strategy": args.get("fix_strategy", ""),
        "category": category,
        "tags": args.get("tags", []), "recorded_at": time.time(), "match_count": 0,
    }
    session.patterns.append(pattern)
    # Also add to global shared pattern store
    _global_patterns.append(dict(pattern))
    if len(_global_patterns) > 500:
        _global_patterns[:] = _global_patterns[-500:]
    return {"content": [{"type": "text", "text": (
        f"📌 Pattern #{pid} recorded: '{args['pattern_name']}'\n"
        f"   Category: {pattern['category']}\n"
        f"   Tags: {', '.join(pattern['tags']) if pattern['tags'] else 'none'}\n"
        f"   Total patterns in session: {len(session.patterns)}"
    )}]}

def tool_pattern_match(args: dict) -> dict:
    """Find matching patterns via Jaccard similarity on tokenized text."""
    session = _get_session(args.get("session_id"))
    query = args["description"]
    # Search both local session patterns AND global shared patterns
    all_patterns = list(session.patterns) + [p for p in _global_patterns if p not in session.patterns]
    category_filter = args.get("category")
    min_score = args.get("min_score", 0.1)
    top_n = min(args.get("top_n", 3), 10)
    if not all_patterns:
        return {"content": [{"type": "text", "text": "No patterns recorded yet. Use pattern_record first."}]}
    candidates = [p for p in all_patterns if not category_filter or p["category"] == category_filter]
    if not candidates:
        return {"content": [{"type": "text", "text": f"No patterns in category '{category_filter}'."}]}
    corpus = [f"{p['pattern_name']} {p['description']} {p['fix_strategy']} {' '.join(p.get('tags',[]))}" for p in candidates]
    all_tokens = [_tokenize(doc) for doc in corpus]
    query_tokens = _tokenize(query)
    scores = []
    for i, tokens in enumerate(all_tokens):
        if not tokens or not query_tokens: continue
        common = set(tokens) & set(query_tokens)
        union = set(tokens) | set(query_tokens)
        sim = len(common) / len(union) if union else 0.0
        if sim >= min_score:
            scores.append((sim, candidates[i]))
    scores.sort(key=lambda x: x[0], reverse=True)
    top = scores[:top_n]
    if not top:
        return {"content": [{"type": "text", "text": "No matching patterns found. Consider recording this as a new pattern with pattern_record."}]}
    # Compact mode — single line
    verbose = args.get("verbose", False)
    if not verbose:
        best = top[0]
        return {"content": [{"type": "text", "text": f"🔍 {best[0]:.0%} match — #{best[1]['id']} {best[1]['pattern_name'][:40]}"}]}
    lines = [f"🔍 Found {len(top)} matching patterns:"]
    for sim, p in top:
        bar = "█" * int(sim * 10) + "░" * (10 - int(sim * 10))
        lines.append(f"\n   {bar} {sim:.0%} — #{p['id']} {p['pattern_name']} [{p['category']}]")
        lines.append(f"   Description: {p['description'][:120]}")
        if p['fix_strategy']: lines.append(f"   Fix: {p['fix_strategy'][:120]}")
        if p.get('tags'): lines.append(f"   Tags: {', '.join(p['tags'])}")
        p['match_count'] = p.get('match_count', 0) + 1  # only matched patterns
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Decision Log — design decision memory
# ═══════════════════════════════════════════════════════════════════════

def tool_decision_log(args: dict) -> dict:
    """Record a design decision with rationale."""
    session = _get_session(args.get("session_id"))
    did = session.next_decision_id
    session.next_decision_id += 1
    category = args.get("category", "other")
    if category not in ("architecture", "tooling", "dependency", "api", "performance", "security", "other"):
        category = "other"
    decision = {
        "id": did, "decision": args.get("decision", ""), "rationale": args.get("rationale", ""),
        "alternatives": args.get("alternatives", []), "context": args.get("context", ""),
        "category": category,
        "revisit_trigger": args.get("revisit_trigger", ""), "recorded_at": time.time(),
    }
    session.decisions.append(decision)
    alt_text = "\n   ".join(f"• {a}" for a in decision['alternatives']) if decision['alternatives'] else "   (none)"
    return {"content": [{"type": "text", "text": (
        f"📋 Decision #{did}: '{decision['decision']}'\n"
        f"   Category: {decision['category']}\n"
        f"   Rationale: {decision['rationale'][:120]}\n"
        f"   Alternatives:\n{alt_text}\n"
        f"   Total decisions: {len(session.decisions)}"
    )}]}

def tool_decision_list(args: dict) -> dict:
    """List recorded decisions, newest first."""
    session = _get_session(args.get("session_id"))
    category_filter = args.get("category")
    limit = min(args.get("limit", 20), 50)
    if not session.decisions:
        return {"content": [{"type": "text", "text": "No decisions recorded yet. Use decision_log to capture design decisions."}]}
    candidates = [d for d in session.decisions if not category_filter or d["category"] == category_filter]
    if not candidates:
        return {"content": [{"type": "text", "text": f"No decisions in category '{category_filter}'."}]}
    # Newest first
    candidates.sort(key=lambda d: d["recorded_at"], reverse=True)
    shown = candidates[:limit]
    lines = [f"📋 Decisions ({len(shown)} shown, {len(session.decisions)} total):"]
    for d in shown:
        lines.append(f"\n   #{d['id']} {d['decision'][:100]} [{d['category']}]")
        lines.append(f"   Why: {d['rationale'][:120]}")
        if d.get('revisit_trigger'): lines.append(f"   🔄 Revisit if: {d['revisit_trigger'][:100]}")
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Wiki — named persistent knowledge pages
# ═══════════════════════════════════════════════════════════════════════

def tool_wiki_create(args: dict) -> dict:
    session = _get_session(args.get("session_id"))
    title = args.get("title", "").strip()
    content = args.get("content", "")
    author = args.get("author", "agent")
    if not title: return {"content": [{"type": "text", "text": "Error: 'title' required."}]}
    existing = title in session.wiki
    session.wiki[title] = {"content": content, "author": author,
        "created_at": session.wiki[title]["created_at"] if existing else time.time(),
        "updated_at": time.time()}
    return {"content": [{"type": "text", "text": f"{'Updated' if existing else 'Created'} wiki: {title} ({len(content)} chars)"}]}

def tool_wiki_read(args: dict) -> dict:
    session = _get_session(args.get("session_id"))
    title = args.get("title", "").strip()
    if not title: return {"content": [{"type": "text", "text": "Error: 'title' required."}]}
    if title not in session.wiki:
        similar = [t for t in session.wiki if title.lower() in t.lower()][:3]
        return {"content": [{"type": "text", "text": f"Page '{title}' not found." + (f" Similar: {', '.join(similar)}" if similar else "")}]}
    w = session.wiki[title]
    return {"content": [{"type": "text", "text": f"{title}\n{w['author']} | {time.strftime('%Y-%m-%d %H:%M', time.localtime(w['updated_at']))}\n\n{w['content']}"}]}

def tool_wiki_update(args: dict) -> dict:
    session = _get_session(args.get("session_id"))
    title = args.get("title", "").strip()
    content = args.get("content", "")
    mode = args.get("mode", "replace")
    author = args.get("author", "agent")
    if not title: return {"content": [{"type": "text", "text": "Error: 'title' required."}]}
    if title not in session.wiki: return {"content": [{"type": "text", "text": f"Page '{title}' not found. Use wiki_create first."}]}
    if mode == "append": session.wiki[title]["content"] += "\n" + content
    else: session.wiki[title]["content"] = content
    session.wiki[title]["updated_at"] = time.time(); session.wiki[title]["author"] = author
    return {"content": [{"type": "text", "text": f"Updated wiki: {title} ({len(session.wiki[title]['content'])} chars)"}]}

def tool_wiki_list(args: dict) -> dict:
    session = _get_session(args.get("session_id"))
    if not session.wiki: return {"content": [{"type": "text", "text": "No wiki pages yet."}]}
    lines = [f"Wiki ({len(session.wiki)} pages):"]
    for title, w in sorted(session.wiki.items(), key=lambda x: x[1]["updated_at"], reverse=True):
        lines.append(f"  {title} — {len(w['content'])} chars, {w['author']} ({time.strftime('%m/%d %H:%M', time.localtime(w['updated_at']))})")
    return {"content": [{"type": "text", "text": f"📋 {len(themes)} themes · {total} thoughts"}], "themes": themes}


# ═══════════════════════════════════════════════════════════════════════
# Token-Efficient Tools — ultra-compact output (1-2 lines) for LLM cost savings
# ═══════════════════════════════════════════════════════════════════════

def tool_state_snapshot(args: dict) -> dict:
    """Ultra-compact system health: 1 line of output, all data in state file."""
    total_thoughts = sum(len(c.get("thoughts", [])) for s in _sessions.values() for c in s.chains.values())
    total_chains = sum(len(s.chains) for s in _sessions.values())
    total_patterns = sum(len(s.patterns) for s in _sessions.values())
    total_works = sum(len(s.works) for s in _sessions.values())
    total_calls = sum(s.tool_calls for s in _sessions.values())
    scored = sum(1 for s in _sessions.values() for c in s.chains.values() for t in c.get("thoughts", []) if t.get("score"))
    avg_score = round(sum(t.get("score", 0) for s in _sessions.values() for c in s.chains.values() for t in c.get("thoughts", []) if t.get("score")) / max(scored, 1), 1)
    return {
        "content": [{"type": "text", "text": f"⚡ {total_chains}c · {total_thoughts}t · {avg_score}★ · {total_patterns}p · {total_works}w · {total_calls} calls"}]
    }

def tool_thought_compress(args: dict) -> dict:
    """Compress a reasoning chain to N key thoughts using TF-IDF similarity.
    Returns only the compressed thoughts, not the full chain history."""
    session = _get_session(args.get("session_id"))
    chain_id = args["chainId"]
    target = min(args.get("targetThoughts", 3), 10)
    chain = session.chains.get(chain_id)
    if not chain:
        return {"content": [{"type": "text", "text": "❌ Chain not found"}]}
    thoughts = chain.get("thoughts", [])
    if len(thoughts) <= target:
        return {"content": [{"type": "text", "text": f"✅ {len(thoughts)} thoughts (under target {target})"}]}
    # Select key thoughts: first, last, and top-scored in between
    first = thoughts[0]["thought"]
    last = thoughts[-1]["thought"]
    middle = sorted(thoughts[1:-1], key=lambda t: t.get("score", 0), reverse=True)[:target - 2]
    compressed = [{"number": 1, "thought": first[:120]}] + \
                 [{"number": t["number"], "thought": t["thought"][:120]} for t in middle] + \
                 [{"number": len(thoughts), "thought": last[:120]}]
    chain["compressed"] = compressed
    return {"content": [{"type": "text", "text": f"✅ Compressed {len(thoughts)}→{len(compressed)} thoughts"}]}

def tool_chain_diff(args: dict) -> dict:
    """Show only what changed between two points in a reasoning chain."""
    session = _get_session(args.get("session_id"))
    chain_id = args["chainId"]
    from_num = args.get("from", 1)
    to_num = args.get("to")
    chain = session.chains.get(chain_id)
    if not chain:
        return {"content": [{"type": "text", "text": "❌ Chain not found"}]}
    thoughts = chain.get("thoughts", [])
    if not to_num:
        to_num = len(thoughts)
    diff_thoughts = [t for t in thoughts if from_num <= t["number"] <= to_num]
    added = sum(1 for t in diff_thoughts if not t.get("isRevision"))
    revised = sum(1 for t in diff_thoughts if t.get("isRevision"))
    branches = sum(1 for t in diff_thoughts if t.get("branchFromThought"))
    return {"content": [{"type": "text", "text": f"Δ #{from_num}→#{to_num}: +{added} · ↻{revised} · 🌿{branches}"}]}

def tool_tool_cache(args: dict) -> dict:
    """Cache expensive tool results. Set: tool_cache(key, value, ttl_seconds).
    Get: tool_cache(key) returns cached value if valid. No output tokens if hit."""
    session = _get_session(args.get("session_id"))
    key = args.get("key", "")
    if not key:
        return {"content": [{"type": "text", "text": "❌ Need key"}]}
    if "value" in args:
        # Set mode
        ttl = args.get("ttl", 300)
        session.chains.setdefault("__cache__", {})[key] = {
            "value": args["value"], "expires": time.time() + ttl
        }
        return {"content": [{"type": "text", "text": "💾 Cached"}]}
    # Get mode
    cache = session.chains.get("__cache__", {}).get(key)
    if cache and cache["expires"] > time.time():
        return {"content": [{"type": "text", "text": "🎯 Cache hit: " + str(cache["value"])[:200]}]}
    return {"content": [{"type": "text", "text": "❌ Cache miss"}]}

def tool_batch_call(args: dict) -> dict:
    """Execute multiple tools in sequence, returning ONE compact output.
    tools: [{"name": "tool_name", "args": {...}}, ...]"""
    tools_list = args.get("tools", [])
    if not tools_list:
        return {"content": [{"type": "text", "text": "❌ No tools specified"}]}
    results = []
    total_ok = 0
    for tool in tools_list[:10]:  # max 10 per batch
        name = tool.get("name", "")
        tool_args = tool.get("args", {})
        handler = HANDLERS.get(name)
        if handler:
            try:
                r = handler(tool_args)
                results.append(f"✅ {name}")
                total_ok += 1
            except:
                results.append(f"❌ {name}")
        else:
            results.append(f"❓ {name}")
    return {"content": [{"type": "text", "text": f"Batch: {total_ok}/{len(tools_list)} OK — {' '.join(results)}"}]}


HANDLERS = {
    "sequential_thinking": tool_sequential_thinking,
    "thought_similarity": tool_thought_similarity,
    "thought_contradiction": tool_thought_contradiction,
    "thought_summarize": tool_thought_summarize,
    "thought_to_plan": tool_thought_to_plan,
    "thought_evaluate": tool_thought_evaluate,
    "thought_bridge": tool_thought_bridge,
    "assume": tool_assume,
    "list_assumptions": tool_list_assumptions,
    "check_assumption": tool_check_assumption,
    "model_add": tool_model_add,
    "model_query": tool_model_query,
    "model_stats": tool_model_stats,
    "model_map": tool_model_map,
    "model_remove": tool_model_remove,
    "model_scan": tool_model_scan,
    "context_preserve": tool_context_preserve,
    "context_check": tool_context_check,
    "work_start": tool_work_start,
    "work_block": tool_work_block,
    "work_done": tool_work_done,
    "work_log": tool_work_log,
    "context_estimate": tool_context_estimate,
    "session_init": tool_session_init,
    "session_list": tool_session_list,
    "agent_message": tool_agent_message,
    "agent_inbox": tool_agent_inbox,
    "collision_check": tool_collision_check,
    "pattern_record": tool_pattern_record,
    "pattern_match": tool_pattern_match,
    "decision_log": tool_decision_log,
    "decision_list": tool_decision_list,
    "wiki_create": tool_wiki_create,
    "wiki_read": tool_wiki_read,
    "wiki_update": tool_wiki_update,
    "wiki_list": tool_wiki_list,
    "state_snapshot": tool_state_snapshot,
    "thought_compress": tool_thought_compress,
    "chain_diff": tool_chain_diff,
    "tool_cache": tool_tool_cache,
    "batch_call": tool_batch_call,
}


# ═══════════════════════════════════════════════════════════════════════
# MCP Server (JSON-RPC over stdio)
# ═══════════════════════════════════════════════════════════════════════

def send(msg: dict) -> None:
    try:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except (OSError, BrokenPipeError, ValueError):
        # Pipe broken or stdout closed — can't send, but don't crash
        pass


def handle_message(msg: dict) -> None:
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-thinking", "version": "2.0.0"}
            }
        })
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        global _tool_calls, _estimated_chars
        _tool_calls += 1
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        # Track which LLM model is executing this tool
        model = tool_args.get("_model", "")
        if model:
            sess = _get_session(tool_args.get("session_id"))
            if sess and sess.model_name != model:
                sess.model_name = model
        handler = HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(tool_args)
                send({"jsonrpc": "2.0", "id": req_id, "result": result})
                _auto_save()  # persist state periodically
            except Exception as e:
                send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": f"Tool error: {e}"}})
        else:
            send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}})
    elif method == "notifications/initialized":
        pass
    else:
        send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


def main() -> None:
    global _start_time
    _start_time = time.time()
    _load_state()
    # Save on graceful shutdown
    import atexit
    atexit.register(_save_state)
    
    # Dashboard HTTP server (optional — pass --dashboard [port])
    if "--dashboard" in sys.argv:
        try:
            idx = sys.argv.index("--dashboard")
            port = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit() else 9876
        except (ValueError, IndexError):
            port = 9876
        _start_dashboard(port)
    
    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_message(msg)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            # Don't let a single bad message kill the server
            try:
                req_id = msg.get("id") if isinstance(msg, dict) else None
                send({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"Internal error: {e}"}})
            except Exception:
                pass  # If even sending the error fails, just continue


_LUMEN_CLIENT_JS = """/**
 * LUMEN Client — WebSocket + binary protocol decoder for dashboards.
 * 
 * Connects to ws://127.0.0.1:9877, receives LUMEN-framed metrics
 * (magic LUM\x01 + flags + u32 length + zlib payload), decompresses,
 * and calls window.renderData(data) on each message.
 * 
 * Falls back to HTTP polling if WebSocket is unavailable.
 */

(function() {
  var ws = null;
  var reconnectTimer = null;
  var WS_URL = 'ws://127.0.0.1:9877';

  function decodeLumenFrame(buffer) {
    /* LUMEN frame: magic(4) + flags(1) + length(4 LE) + payload */
    var data = new Uint8Array(buffer);
    if (data[0] !== 76 || data[1] !== 85 || data[2] !== 77 || data[3] !== 1) {
      return null; // not LUMEN
    }
    var flags = data[4];
    var length = new DataView(buffer).getUint32(5, true);
    var payload = new Uint8Array(buffer, 9, length);
    
    if (flags & 1) {
      /* zlib decompress */
      try {
        var ds = new DecompressionStream('deflate');
        var writer = ds.writable.getWriter();
        writer.write(payload);
        writer.close();
        return ds.readable;
      } catch(e) {
        /* DecompressionStream not available — return raw */
        var decoder = new TextDecoder();
        return decoder.decode(payload);
      }
    }
    var decoder = new TextDecoder();
    return decoder.decode(payload);
  }

  function handleMessage(event) {
    var result = decodeLumenFrame(event.data);
    if (!result) return;
    
    if (typeof result === 'string') {
      /* Already decoded */
      try {
        var data = JSON.parse(result);
        if (window.renderData) window.renderData(data);
      } catch(e) {}
    } else {
      /* ReadableStream from DecompressionStream */
      result.getReader().read().then(function(r) {
        try {
          var json = new TextDecoder().decode(r.value);
          var data = JSON.parse(json);
          if (window.renderData) window.renderData(data);
        } catch(e) {}
      });
    }
  }

  function connect() {
    try {
      ws = new WebSocket(WS_URL);
      ws.binaryType = 'arraybuffer';
      
      ws.onopen = function() {
        var label = document.getElementById('status-label');
        if (label) { label.textContent = 'Live·LUMEN'; label.className = 'status-text green'; }
        var dot = document.getElementById('status-dot');
        if (dot) dot.className = 'dot live';
      };
      
      ws.onmessage = handleMessage;
      
      ws.onclose = function() {
        ws = null;
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connect, 5000);
      };
      
      ws.onerror = function() {
        ws = null;
      };
    } catch(e) {
      ws = null;
    }
  }

  connect();
})();
"""

def _start_dashboard(port: int = 9876) -> None:
    """Start a lightweight HTTP metrics server on a daemon thread.
    
    Exposes /metrics (JSON) for consumption by skynet lumen-dash or any monitoring tool.
    Runs on localhost only — no external access.
    """
    import threading, http.server as _http
    
    global _lumen_ws
    try:
        from lumen_transport import LumenWS
        _lumen_ws = LumenWS(port=port + 1)
        _lumen_ws.start()
        _safe_print(f"[lumen-dashboard] LUMEN WebSocket on ws://127.0.0.1:{port + 1}")
    except Exception as e:
        _lumen_ws = None
        _safe_print(f"[lumen-dashboard] LUMEN WS unavailable: {e}")

    # Load dashboard HTML from file
    _dashboard_html_path = Path(__file__).parent / "dashboard.html"
    _safe_print(f"[lumen-dashboard] Loading dashboard from {_dashboard_html_path}")
    if _dashboard_html_path.exists():
        with open(_dashboard_html_path, "r", encoding="utf-8") as f:
            _DASHBOARD_HTML = f.read()
    else:
        _DASHBOARD_HTML = "<html><body><h1>LUMEN Dashboard</h1><p>dashboard.html not found</p></body></html>"

    class MetricsHandler(_http.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/" or self.path == "/index.html":
                body = _DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/metrics":
                data = _build_metrics()
                body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                try:
                    if _lumen_ws is not None:
                        _lumen_ws.broadcast(data)
                except:
                    pass
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/health":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            elif self.path.startswith("/inbox"):
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                target = qs.get("session", ["default"])[0]
                msgs = [m for m in _agent_messages if m["to_session"] == target or m["to_session"] == "*"]
                body = json.dumps(msgs[-50:], ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/model"):
                # GET /model or GET /model?entity=X
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                entity_name = qs.get("entity", [None])[0]
                session_id = qs.get("session_id", [_DEFAULT_SESSION])[0]
                session = _sessions.get(session_id, _sessions.get(_DEFAULT_SESSION))
                if entity_name:
                    if entity_name in session.model:
                        data = dict(session.model[entity_name])
                        data["entity"] = entity_name
                        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": f"Entity '{entity_name}' not found"}).encode())
                else:
                    # Return all entities
                    all_entities = {e: dict(session.model[e]) for e in session.model}
                    body = json.dumps(all_entities, ensure_ascii=False, indent=2).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            elif self.path == "/collisions":
                now = time.time(); window = 300
                from collections import defaultdict
                by_file = defaultdict(list)
                for t in _file_touches:
                    if now - t["timestamp"] < window:
                        by_file[t["path"]].append(t)
                collisions = []
                for path, touches in by_file.items():
                    sessions = set(t["session_id"] for t in touches)
                    if len(sessions) > 1:
                        collisions.append({"path": path, "sessions": list(sessions), "count": len(touches)})
                body = json.dumps({"window_s": window, "collisions": collisions}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/chain"):
                from urllib.parse import urlparse, parse_qs
                qs = parse_qs(urlparse(self.path).query)
                cid = qs.get("chain_id", [None])[0]
                if not cid:
                    self.send_response(400); self.end_headers()
                    self.wfile.write(b'{"error":"chain_id required"}'); return
                found = None
                for sid, sess in _sessions.items():
                    if cid in sess.chains:
                        chain = sess.chains[cid]
                        thoughts = chain.get("thoughts", [])
                        found = {
                            "chain_id": cid,
                            "session": sid,
                            "version": chain.get("version", 1),
                            "created_at": chain.get("created_at", 0),
                            "updated_at": chain.get("updated_at", 0),
                            "total_thoughts": len(thoughts),
                            "plan": chain.get("plan"),
                            "clusters": chain.get("clusters", []),
                            "thoughts": [{
                                "number": t["number"],
                                "thought": t["thought"][:300],
                                "score": t.get("score"),
                                "is_revision": t.get("isRevision", False),
                                "has_branch": bool(t.get("branchId")),
                                "revises": t.get("revisesThought"),
                            } for t in thoughts]
                        }
                        break
                if found:
                    body = json.dumps(found, ensure_ascii=False, indent=2).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404); self.end_headers()
                    self.wfile.write(json.dumps({"error": "chain not found"}).encode())
            elif self.path == "/benchmarks":
                # Phase F scorecard: compute real metrics from live data
                total_thoughts = sum(len(c.get("thoughts",[])) for s in _sessions.values() for c in s.chains.values())
                total_chains = sum(len(s.chains) for s in _sessions.values())
                total_patterns = sum(len(s.patterns) for s in _sessions.values())
                total_tool_calls = sum(s.tool_calls for s in _sessions.values())
                total_works = sum(len(s.works) for s in _sessions.values())
                total_wiki = sum(len(s.wiki) for s in _sessions.values())
                total_bridges = sum(len(s.bridges) for s in _sessions.values())
                total_decisions = sum(len(s.decisions) for s in _sessions.values())
                
                # Pattern recall rate
                pattern_hits = sum(p.get("match_count", 0) for s in _sessions.values() for p in s.patterns)
                pattern_total = sum(1 for s in _sessions.values() for p in s.patterns if p.get("match_count", 0) > 0)
                
                # Score stats
                all_scores = []
                for s in _sessions.values():
                    for c in s.chains.values():
                        for t in c.get("thoughts", []):
                            if t.get("score"): all_scores.append(t["score"])
                avg_score = round(sum(all_scores)/len(all_scores), 1) if all_scores else None
                
                # Cross-session value
                sessions_count = len(_sessions)
                cross_session_bridges = sum(1 for s in _sessions.values() for b in s.bridges if b.get("score", 0) > 0.3)
                
                scorecard = {
                    "phase": "F — Intelligence as Commodity",
                    "proposition": "LUMEN cognitive exoskeleton makes any model smarter",
                    "metrics": {
                        "total_thoughts": total_thoughts,
                        "total_chains": total_chains,
                        "avg_score": avg_score,
                        "pattern_recall": {
                            "total_patterns": total_patterns,
                            "patterns_with_hits": pattern_total,
                            "total_hits": pattern_hits,
                            "description": "Bugs caught by pattern matching before reaching code"
                        },
                        "knowledge_accumulation": {
                            "wiki_pages": total_wiki,
                            "decisions_logged": total_decisions,
                            "cross_session_bridges": cross_session_bridges,
                            "description": "Knowledge that survives context windows and sessions"
                        },
                        "work_tracking": {
                            "total_works": total_works,
                            "completed": sum(1 for s in _sessions.values() for w in s.works if w.get("status") == "done"),
                            "description": "Task tracking with durations across sessions"
                        },
                        "tool_efficiency": {
                            "total_calls": total_tool_calls,
                            "sessions": sessions_count,
                            "calls_per_session": round(total_tool_calls/max(sessions_count,1), 1),
                            "description": "How much the exoskeleton is being used"
                        }
                    },
                    "verdict": "READY" if total_chains > 0 else "NEEDS_DATA",
                    "tagline": "When a 7B with LUMEN beats a 70B alone, intelligence is a commodity."
                }
                body = json.dumps(scorecard, ensure_ascii=False, indent=2).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/lumen-client.js":
                body = _LUMEN_CLIENT_JS.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not found -- try /metrics or /health")
        
        def do_POST(self):
            if self.path.startswith("/model"):
                from urllib.parse import urlparse, parse_qs
                content_len = int(self.headers.get('Content-Length', 0))
                body_raw = self.rfile.read(content_len) if content_len else b'{}'
                params = json.loads(body_raw)
                action = params.get("_action", "upsert")  # upsert or delete
                entity = params.get("entity", "")
                session_id = params.get("session_id", _DEFAULT_SESSION)
                if session_id not in _sessions:
                    _sessions[session_id] = Session(label=session_id)
                session = _sessions[session_id]
                if action == "delete":
                    if entity in session.model:
                        del session.model[entity]
                        _update_dependents(session)
                        _save_state()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({"deleted": entity}).encode())
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(json.dumps({"error": f"Entity '{entity}' not found"}).encode())
                else:
                    if not entity:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b'{"error":"entity required"}')
                        return
                    entity = entity.replace("\\", "/")
                    existing = entity in session.model
                    session.model[entity] = {
                        "role": params.get("role", "other"),
                        "deps": list(params.get("deps", [])),
                        "dependents": [],
                        "notes": params.get("notes", ""),
                        "properties": dict(params.get("properties", {})) if isinstance(params.get("properties"), dict) else {},
                        "added_at": time.time(),
                    }
                    _update_dependents(session)
                    _save_state()
                    act = "updated" if existing else "created"
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"action": act, "entity": entity}).encode())
            elif self.path == "/clear-chains":
                try:
                    content_len = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(content_len) if content_len else b'{}'
                    params = json.loads(body)
                    session_id = params.get("session_id", _DEFAULT_SESSION)
                    if session_id in _sessions:
                        count = len(_sessions[session_id].chains)
                        _sessions[session_id].chains.clear()
                        _save_state()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"cleared": count, "session": session_id}).encode())
                    else:
                        self.send_response(404)
                        self.end_headers()
                        self.wfile.write(b'{"error":"Session not found"}')
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/clear-bridges":
                for sess in _sessions.values():
                    sess.bridges.clear()
                _save_state()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"cleared":"all bridges"}')
            elif self.path == "/touch":
                try:
                    content_len = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(content_len) if content_len else b'{}'
                    params = json.loads(body)
                    sid = params.get("session_id", _DEFAULT_SESSION)
                    path = params.get("path", "")
                    if path:
                        _file_touches.append({"session_id": sid, "path": path, "timestamp": time.time()})
                        if len(_file_touches) > 500: _file_touches[:] = _file_touches[-500:]
                        _save_state()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"touches": len(_file_touches)}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/collisions":
                now = time.time()
                window = 300  # 5 minutes
                # Group touches by file path
                from collections import defaultdict
                by_file = defaultdict(list)
                for t in _file_touches:
                    if now - t["timestamp"] < window:
                        by_file[t["path"]].append(t)
                collisions = []
                for path, touches in by_file.items():
                    sessions = set(t["session_id"] for t in touches)
                    if len(sessions) > 1:
                        collisions.append({"path": path, "sessions": list(sessions), "count": len(touches)})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"window_s": window, "collisions": collisions}).encode())
            elif self.path == "/wiki":
                try:
                    content_len = int(self.headers.get('Content-Length', 0))
                    raw = self.rfile.read(content_len) if content_len else b'{}'
                    params = json.loads(raw)
                    title = params.get("title", "").strip()
                    content = params.get("content", "")
                    author = params.get("author", "dashboard")
                    if not title:
                        self.send_response(400); self.end_headers()
                        self.wfile.write(b'{"error":"title required"}'); return
                    sess = _get_session(params.get("session_id", _DEFAULT_SESSION))
                    existing = title in sess.wiki
                    sess.wiki[title] = {"content": content, "author": author,
                        "created_at": sess.wiki[title]["created_at"] if existing else time.time(),
                        "updated_at": time.time()}
                    _save_state()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"created": title, "chars": len(content)}).encode())
                except Exception as e:
                    self.send_response(500); self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/claim":
                try:
                    content_len = int(self.headers.get('Content-Length', 0))
                    raw = self.rfile.read(content_len) if content_len else b'{}'
                    params = json.loads(raw)
                    filepath = params.get("path", "").strip()
                    sid = params.get("session_id", _DEFAULT_SESSION)
                    ttl = params.get("ttl", 60)
                    if not filepath:
                        self.send_response(400); self.end_headers()
                        self.wfile.write(b'{"error":"path required"}'); return
                    existing = _file_claims.get(filepath)
                    if existing and existing.get("expires_at", 0) > time.time() and existing.get("owner") != sid:
                        existing.setdefault("requests", []).append({"session": sid, "timestamp": time.time()})
                        _save_state()
                        self.send_response(409)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "conflict", "owner": existing["owner"],
                            "expires_in": round(existing["expires_at"] - time.time(), 1)}).encode())
                    else:
                        _file_claims[filepath] = {"owner": sid, "expires_at": time.time() + ttl,
                            "status": "active", "requests": existing.get("requests", []) if existing else []}
                        _save_state()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json")
                        self.end_headers()
                        self.wfile.write(json.dumps({"status": "claimed", "expires_in": ttl}).encode())
                except Exception as e:
                    self.send_response(500); self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            elif self.path == "/release":
                try:
                    content_len = int(self.headers.get('Content-Length', 0))
                    raw = self.rfile.read(content_len) if content_len else b'{}'
                    params = json.loads(raw)
                    filepath = params.get("path", "").strip()
                    sid = params.get("session_id", _DEFAULT_SESSION)
                    if filepath in _file_claims and _file_claims[filepath].get("owner") == sid:
                        requests = _file_claims[filepath].get("requests", [])
                        if requests:
                            next_owner = requests[0]["session"]
                            _file_claims[filepath] = {"owner": next_owner, "expires_at": time.time() + 60,
                                "status": "transferred", "requests": requests[1:]}
                        else:
                            del _file_claims[filepath]
                        _save_state()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "released"}).encode())
                except Exception as e:
                    self.send_response(500); self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"Unknown endpoint"}')
        

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def log_message(self, *args):
            pass  # silence HTTP logs
    
    def _build_metrics():
        global _last_state_mtime
        # Reload state from file if it was updated by another process (e.g. SHM server)
        if _STATE_FILE.exists():
            try:
                file_mtime = _STATE_FILE.stat().st_mtime
                if file_mtime > _last_state_mtime:
                    with open(_STATE_FILE, "r", encoding="utf-8") as f:
                        state = json.load(f)
                    global _sessions, _preserved, _call_timeline, _next_session_num
                    _sessions = {sid: Session.from_dict(sd) for sid, sd in state.get("sessions", {}).items()}
                    _next_session_num = state.get("next_session_num", 1)
                    _preserved = state.get("preserved", [])
                    if "timeline" in state:
                        _call_timeline[:] = state["timeline"]
                    global _session_presence, _file_touches, _file_claims
                    _session_presence = state.get("presence", {})
                    _file_touches = state.get("file_touches", [])
                    _file_claims = state.get("file_claims", {})
                    _last_state_mtime = file_mtime
            except Exception:
                pass
        
        total_chains = sum(len(s.chains) for s in _sessions.values())
        total_patterns = sum(len(s.patterns) for s in _sessions.values())
        total_decisions = sum(len(s.decisions) for s in _sessions.values())
        total_model = sum(len(s.model) for s in _sessions.values())
        total_assumptions = sum(len(s.assumptions) for s in _sessions.values())
        total_works = sum(len(s.works) for s in _sessions.values())
        total_tool_calls = sum(s.tool_calls for s in _sessions.values())
        
        # Per-session breakdown
        sessions_data = {}
        for sid, sess in _sessions.items():
            sessions_data[sid] = {
                "label": sess.label,
                "chains": len(sess.chains),
                "patterns": len(sess.patterns),
                "decisions": len(sess.decisions),
                "model_entities": len(sess.model),
                "assumptions": len(sess.assumptions),
                "works": len(sess.works),
                "tool_calls": sess.tool_calls,
                "model": sess.model_name or "unknown",
                "created_at": sess.created_at,
                "updated_at": sess.updated_at,
            }
        
        # Rich chain detail: scores, thoughts, branches, revisions, previews
        chains_detail = []
        all_scores = []
        total_thoughts = 0
        total_branches = 0
        total_revisions = 0
        
        for sid, sess in _sessions.items():
            for cid, chain in sess.chains.items():
                thoughts = chain.get("thoughts", [])
                thought_count = len(thoughts)
                total_thoughts += thought_count
                
                scores = [t.get("score") for t in thoughts if t.get("score") is not None]
                all_scores.extend(scores)
                
                branches = [t for t in thoughts if t.get("branchId")]
                revisions = [t for t in thoughts if t.get("isRevision")]
                total_branches += len(branches)
                total_revisions += len(revisions)
                
                chains_detail.append({
                    "chain_id": cid,
                    "session": sid,
                    "thoughts": thought_count,
                    "score_avg": round(sum(scores) / len(scores), 1) if scores else None,
                    "score_max": max(scores) if scores else None,
                    "branches": len(branches),
                    "revisions": len(revisions),
                    "version": chain.get("version", 1),
                    "contradictions": chain.get("contradictions", 0),
                    "plan": chain.get("plan"),
                    "clusters": chain.get("clusters", [])[:3],
                    "similarities": chain.get("similarities", [])[-3:],
                    "created_at": chain.get("created_at", 0),
                    "updated_at": chain.get("updated_at", 0),
                    "preview": thoughts[0].get("thought", "")[:120] if thoughts else "",
                })
        
        chains_detail.sort(key=lambda c: c["thoughts"], reverse=True)
        
        # Score stats
        score_avg = round(sum(all_scores) / len(all_scores), 1) if all_scores else None
        score_max = max(all_scores) if all_scores else None
        score_min = min(all_scores) if all_scores else None
        
        # Bridge data
        bridges = []
        for sid, sess in _sessions.items():
            if hasattr(sess, 'bridges'):
                bridges.extend(sess.bridges)
        bridges.sort(key=lambda b: b.get("score", 0), reverse=True)
        
        # Extract plans and clusters from chains
        all_plans = []
        all_clusters = []
        for sid, sess in _sessions.items():
            for cid, chain in sess.chains.items():
                if chain.get("plan"):
                    all_plans.append({"chain_id": cid, "session": sid, **chain["plan"]})
                for cl in chain.get("clusters", []):
                    all_clusters.append({"chain_id": cid, "session": sid, **cl})
        
        return {
            "server": "lumen-thinking",
            "version": "3.0.0",
            "uptime_seconds": time.time() - _start_time if "_start_time" in dir() else 0,
            "sessions": len(_sessions),
            "totals": {
                "chains": total_chains,
                "thoughts": total_thoughts,
                "patterns": total_patterns,
                "decisions": total_decisions,
                "model_entities": total_model,
                "assumptions": total_assumptions,
                "works": total_works,
                "tool_calls": total_tool_calls,
                "preserved_contexts": len(_preserved),
                "branches": total_branches,
                "revisions": total_revisions,
            },
            "scores": {
                "avg": score_avg,
                "max": score_max,
                "min": score_min,
                "total_rated": len(all_scores),
                "unrated": total_thoughts - len(all_scores),
            },
            "sessions_detail": sessions_data,
            "chains": chains_detail[:20],
            "bridges": bridges[:10],
            "plans": all_plans[:10],
            "clusters": all_clusters[:10],
            "works": [{"id": w["id"], "item": w["item"], "status": w["status"],
                "category": w.get("category", "other"), "session": sid,
                "duration_seconds": (round(w["done_at"] - w["started_at"], 1) if w.get("done_at") and w.get("started_at") else round(time.time() - w["started_at"], 1) if w.get("started_at") else None),
                "started_at": w.get("started_at"), "done_at": w.get("done_at")}
                for sid, sess in _sessions.items() for w in sess.works][:20],
            "wiki": [{"title": t, "chars": w["content"][:2000], "author": w["author"], "updated": w["updated_at"]} for t, w in sorted(
                ((t, w) for sid, sess in _sessions.items() for t, w in sess.wiki.items()),
                key=lambda x: x[1]["updated_at"], reverse=True)[:20]],
            "top_chains": chains_detail[:10],
            "preserved": [{"label": p.get("label",""), "priority": p["priority"], "content": p["content"][:200]} for p in _preserved[-5:]],
            "model": [{"entity": path, "role": node.get("role","?"), "deps": len(node.get("deps",[])), "notes": node.get("notes","")[:80]} for sid, sess in _sessions.items() for path, node in sess.model.items()][:20],
            "assumptions": [{"id": a["id"], "statement": a["statement"][:120], "status": a["status"], "category": a.get("category","")} for sid, sess in _sessions.items() for a in sess.assumptions][:20],
            "decisions": [{"id": d["id"], "decision": d["decision"][:120], "category": d["category"], "rationale": d["rationale"][:80]} for sid, sess in _sessions.items() for d in sess.decisions][:20],
            "presence": _session_presence,
            "claims": {f: {"owner": c["owner"], "expires_in": round(c["expires_at"]-time.time(),1) if c.get("expires_at") else 0, "status": c.get("status","active"), "requests": c.get("requests",[])} for f,c in _file_claims.items() if c.get("expires_at",0) > time.time()},
            "timeline": _call_timeline[-60:],
        }
    
    server = _http.HTTPServer(("127.0.0.1", port), MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="lumen-dashboard")
    thread.start()
    _safe_print(f"[lumen-dashboard] Metrics server on http://127.0.0.1:{port}/metrics")


if __name__ == "__main__":
    main()
