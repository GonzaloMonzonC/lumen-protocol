#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      LUMEN AGENT LOOP  -  v1.0                             ║
║               "LUMEN learns your traffic. It gets better."                 ║
╚══════════════════════════════════════════════════════════════════════════════╝

Simulates an LLM agent calling MCP tools across a conversation,
demonstrating how LUMEN''s session dictionary progressively reduces
wire size as it learns repeated key patterns.

Usage:
    python agent_loop.py                  # default: 30 turns
    python agent_loop.py --turns 50      # custom turns
    python agent_loop.py --no-graph      # table only

Requires: pip install -e implementations/python
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import textwrap
from dataclasses import dataclass
from typing import Any

try:
    from lumen import compress_value
    from lumen.frame import build_size, FLAG_COMPRESSED, TYPE_NOTIFY, TYPE_RESPONSE
    from lumen.dict import (
        clear_session_dict,
        register_session_key,
        lookup_dict_id,
    )
except ImportError:
    print("\n  LUMEN Python package required.")
    print("  Install: pip install -e implementations/python")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Agent simulation: realistic MCP conversation patterns
# ═══════════════════════════════════════════════════════════════════════════════

# Common keys that appear in MCP tool calls repeatedly
AGENT_KEYS = [
    "file_path", "line_number", "column", "end_line", "uri",
    "start_line", "content", "operation", "severity", "pattern",
    "function_name", "class_name", "module", "import_path",
    "test_name", "test_file", "expected", "actual", "diff",
    "commit_hash", "branch", "repository", "author",
    "dependency", "version", "constraint", "latest",
    "port", "host", "timeout_ms", "retry_count",
    "config_key", "config_value", "environment",
]

TOOL_NAMES = [
    "search_code", "read_file", "write_file", "execute_command",
    "list_directory", "get_diagnostics", "semantic_search",
    "manage_memory", "fetch_webpage", "create_rule",
]


def make_initialize() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
                "resources": {"subscribe": True},
                "prompts": {},
            },
            "clientInfo": {
                "name": "lumen-agent-demo",
                "version": "1.0.0",
            },
        },
    }


def make_tools_list() -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
    }


def make_tool_call(turn: int, tool_idx: int) -> dict:
    """Generate a realistic tool call request."""
    tool = TOOL_NAMES[tool_idx % len(TOOL_NAMES)]
    # Build arguments using some AGENT_KEYS deterministically but varied
    key_start = (turn * 3 + tool_idx) % (len(AGENT_KEYS) - 4)
    keys = AGENT_KEYS[key_start:key_start + 4]
    args = {}
    for i, k in enumerate(keys):
        if k.endswith("_ms") or k.endswith("_count"):
            args[k] = random.randint(100, 5000)
        elif k.endswith("_line") or k == "line_number":
            args[k] = random.randint(1, 500)
        elif k in ("host", "environment", "branch", "module"):
            args[k] = f"value_{turn}_{i}"
        else:
            args[k] = f"arg_val_{turn}_{i:03d}"
    return {
        "jsonrpc": "2.0",
        "id": 100 + turn,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": args,
        },
    }


def make_tool_result(turn: int, tool_idx: int) -> dict:
    """Generate a realistic tool call result."""
    tool = TOOL_NAMES[tool_idx % len(TOOL_NAMES)]
    key_start = (turn * 5 + tool_idx) % (len(AGENT_KEYS) - 6)
    keys = AGENT_KEYS[key_start:key_start + 6]
    result_data = {}
    for i, k in enumerate(keys):
        if k.endswith("_hash"):
            result_data[k] = f"abc123def456{i}"
        elif k in ("commit_hash",):
            result_data[k] = f"d34db33f{i:04d}"
        elif k in ("host", "port"):
            result_data[k] = f"res_{turn}_{i}"
        else:
            result_data[k] = f"result_{turn}_{i:03d}"
    return {
        "jsonrpc": "2.0",
        "id": 100 + turn,
        "result": {
            "content": [
                {"type": "text", "text": f"Tool {tool} executed successfully."}
            ],
            "data": result_data,
        },
    }


@dataclass
class TurnResult:
    turn: int
    json_bytes: int
    lumen_cold_bytes: int
    lumen_warm_bytes: int


def measure_wire(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def compress_wire(payload: dict) -> int:
    """Wire size after LUMEN compress + frame."""
    c = compress_value(payload)
    return build_size(payload_len=len(c))


# ── Session dictionary management ────────────────────────────────────────────

def feed_session_keys(payload: dict) -> int:
    """Learn all string keys from a payload into the session dictionary.
    Returns number of new keys registered."""
    new_keys = 0
    keys_to_learn = extract_keys(payload)
    # Find next available session dict slot (0x80..0xFE)
    slot = 0x80
    for key in keys_to_learn:
        if lookup_dict_id(key) is not None:
            continue  # Already in static or session dict
        # Find first free slot
        while slot < 0xFF:
            from lumen.dict import resolve_dict_id
            if resolve_dict_id(slot) is None:
                break
            slot += 1
        if slot >= 0xFF:
            break
        if register_session_key(key, slot):
            new_keys += 1
            slot += 1
    return new_keys


def extract_keys(obj: Any, max_keys: int = 127) -> set[str]:
    """Recursively extract all object keys from a JSON-compatible value."""
    keys: set[str] = set()
    _walk(obj, keys, max_keys)
    return keys


def _walk(obj: Any, keys: set[str], max_keys: int) -> None:
    if len(keys) >= max_keys:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k not in keys:
                keys.add(k)
                if len(keys) >= max_keys:
                    return
            _walk(v, keys, max_keys)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, keys, max_keys)


# ═══════════════════════════════════════════════════════════════════════════════
# Main simulation
# ═══════════════════════════════════════════════════════════════════════════════

def run_agent_loop(n_turns: int) -> list[TurnResult]:
    clear_session_dict()
    random.seed(42)

    turns: list[TurnResult] = []

    # Turn 0: initialize
    init = make_initialize()
    json_wire = measure_wire(init)
    lumen_cold = compress_wire(init)
    feed_session_keys(init)
    lumen_warm = compress_wire(init)
    turns.append(TurnResult(0, json_wire, lumen_cold, lumen_warm))

    # Turn 1: tools/list
    tl = make_tools_list()
    json_wire = measure_wire(tl)
    lumen_cold = compress_wire(tl)
    feed_session_keys(tl)
    lumen_warm = compress_wire(tl)
    turns.append(TurnResult(1, json_wire, lumen_cold, lumen_warm))

    # Turns 2..N: alternating tool calls and results
    for turn in range(2, n_turns + 1):
        if turn % 2 == 0:
            msg = make_tool_call(turn, turn // 2)
        else:
            msg = make_tool_result(turn, (turn - 1) // 2)

        json_wire = measure_wire(msg)
        lumen_cold = compress_wire(msg)
        feed_session_keys(msg)
        lumen_warm = compress_wire(msg)
        turns.append(TurnResult(turn, json_wire, lumen_cold, lumen_warm))

    return turns

# ═══════════════════════════════════════════════════════════════════════════════
# Output formatting
# ═══════════════════════════════════════════════════════════════════════════════

def fmt_bytes(b: int) -> str:
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def print_header() -> None:
    print()
    print("  " + "\u2550" * 74)
    print("  \u2551" + f"{"LUMEN AGENT LOOP  -  Session Dictionary Demo":^72}" + "\u2551")
    print("  \u2551" + f"{"\"It gets better the more you use it.\"":^72}" + "\u2551")
    print("  " + "\u2550" * 74)
    print()


def print_agent_narrative(turns: list[TurnResult]) -> None:
    """Print the story of what the agent is doing."""
    print("  Simulating: LLM Agent working on a coding task...")
    print()
    narrative = [
        "  Agent: \"Let me initialize the MCP connection...\"",
        "  Agent: \"What tools are available?\"",
        "  Agent: \"Search for TODO comments across the project\"",
        "  Server: [returns 47 matches across 12 files]",
        "  Agent: \"Read the auth module to understand the flow\"",
        "  Server: [returns auth.rs with 320 lines]",
        "  Agent: \"Check for lint errors in auth.rs\"",
        "  Server: [3 warnings: unused import, long function, missing docs]",
        "  Agent: \"Fix the unused import in auth.rs\"",
        "  Server: [file updated successfully]",
        "  Agent: \"Now search for similar patterns in other modules\"",
        "  Server: [found 12 files with similar patterns]",
    ]
    for i, line in enumerate(narrative):
        if i < len(narrative):
            print(line)
    if len(turns) > 12:
        print(f"  ... (continuing for {len(turns)} turns) ...")
    print()


def print_turn_table(turns: list[TurnResult]) -> float:
    """Print table of results and return aggregate savings."""
    print()
    print("  " + "\u2550" * 74)
    print(f"  \u2551 {"Turn":<6} {"JSON-RPC":>10} {"LUMEN Cold":>11} {"LUMEN Warm":>11} {"Savings":>11} {"Dict":>7} \u2551")
    print("  \u2551 " + "-" * 68 + " \u2551")

    # Calculate running dict size
    from lumen.dict import session_dict_size

    cumulative_json = 0
    cumulative_lumen_cold = 0
    cumulative_lumen_warm = 0

    for i, t in enumerate(turns):
        cumulative_json += t.json_bytes
        cumulative_lumen_cold += t.lumen_cold_bytes
        cumulative_lumen_warm += t.lumen_warm_bytes

        savings = ((t.json_bytes - t.lumen_warm_bytes) / t.json_bytes * 100) if t.json_bytes > 0 else 0
        marker = ""
        if savings >= 90:
            marker = " >>>"
        elif savings >= 70:
            marker = " >>"
        elif savings >= 40:
            marker = " >"

        label = f"#{t.turn}"
        # Show dict size only every few turns
        if i % 5 == 0 or i == len(turns) - 1:
            dict_size = session_dict_size()
            dict_str = f"{dict_size}"
        else:
            dict_str = "."

        print(
            f"  \u2551 {label:<6} {fmt_bytes(t.json_bytes):>10} "
            f"{fmt_bytes(t.lumen_cold_bytes):>11} {fmt_bytes(t.lumen_warm_bytes):>11} "
            f"{savings:.0f}%{marker:>4} {dict_str:>6} \u2551"
        )

    print("  \u2551 " + "-" * 68 + " \u2551")
    total_warm_savings = (
        (cumulative_json - cumulative_lumen_warm) / cumulative_json * 100
    ) if cumulative_json > 0 else 0

    print(
        f"  \u2551 {"TOTAL":<6} {fmt_bytes(cumulative_json):>10} "
        f"{fmt_bytes(cumulative_lumen_cold):>11} {fmt_bytes(cumulative_lumen_warm):>11} "
        f"{total_warm_savings:.1f}%{" >>>" if total_warm_savings >= 80 else "":>4} {"":>6} \u2551"
    )
    print("  " + "\u2550" * 74)

    # Key insight
    print()
    print(f"  Key insight: With session dict, savings reach {total_warm_savings:.1f}% cumulative.")
    print(f"  Cold start (static dict only) would save less. LUMEN learns YOUR traffic.")
    print()

    return total_warm_savings


def print_ascii_graph(turns: list[TurnResult]) -> None:
    """Draw an ASCII graph of savings over time."""
    print()
    print("  " + "\u2550" * 74)
    print(f"  \u2551 {"Savings Progression Over Time":^72} \u2551")
    print("  " + "\u2550" * 74)
    print()

    max_turns = max(t.turn for t in turns)
    graph_width = 60

    # Build data points
    savings_vals: list[float] = []
    for t in turns:
        if t.json_bytes > 0:
            sv = (t.json_bytes - t.lumen_warm_bytes) / t.json_bytes * 100
        else:
            sv = 0
        savings_vals.append(sv)

    # Y-axis: 0 to 100
    y_levels = [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0]
    x_step = graph_width / max_turns if max_turns > 0 else 1

    for y in y_levels:
        label = f"  {y:>3}% "
        line = label
        for x_val in range(graph_width + 1):
            turn_idx = int(x_val / x_step) if x_step > 0 else 0
            turn_idx = min(turn_idx, len(savings_vals) - 1)
            sv = savings_vals[turn_idx] if savings_vals else 0

            if x_val == 0:
                line += "\u251c" if y < 100 else "\u250c"
            elif y == 0:
                line += "\u2534" if x_val % 10 == 0 else "\u2500"
            elif sv >= y:
                # Check adjacent to draw blocks
                next_idx = min(turn_idx + 1, len(savings_vals) - 1)
                prev_idx = max(turn_idx - 1, 0)
                next_sv = savings_vals[next_idx] if savings_vals else 0
                prev_sv = savings_vals[prev_idx] if savings_vals else 0

                if abs(sv - y) < 5 or (sv >= y and prev_sv >= y - 3):
                    line += "\u2588"
                elif sv >= y - 5:
                    line += "\u2592"
                else:
                    line += " "
            else:
                line += " "
        print(line)

    # X-axis labels
    x_label = "       "
    for i in range(0, max_turns + 1, 5):
        pos = int(i * x_step)
        label = f"{i}"
        while len(x_label) < pos + 7:
            x_label += " "
        x_label = x_label[:pos + 7] + label
    print(x_label[:graph_width + 10])
    print()


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LUMEN Agent Loop — demonstrate session dictionary benefits"
    )
    parser.add_argument("--turns", type=int, default=30,
                        help="Number of conversation turns (default: 30)")
    parser.add_argument("--no-graph", action="store_true",
                        help="Skip ASCII graph, table only")
    parser.add_argument("--no-narrative", action="store_true",
                        help="Skip agent narrative text")
    args = parser.parse_args()

    print_header()

    turns = run_agent_loop(args.turns)

    if not args.no_narrative:
        print_agent_narrative(turns)

    print_turn_table(turns)

    if not args.no_graph:
        print_ascii_graph(turns)

    print("  LUMEN: The more you use it, the smaller your wire gets.")
    print()


if __name__ == "__main__":
    main()
