#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    LUMEN COST CALCULATOR  -  v1.0                          ║
║                 "How much is JSON-RPC costing you?"                        ║
╚══════════════════════════════════════════════════════════════════════════════╝

A data-driven projection tool for engineering leaders evaluating the financial
and operational impact of switching MCP transport from JSON-RPC to LUMEN.

Usage:
    python cost_calculator.py                          # interactive
    python cost_calculator.py --monthly-calls 50M      # custom volume
    python cost_calculator.py --csv report.csv         # export CSV

Requires: pip install -e implementations/python
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Any

try:
    from lumen import compress_value
    from lumen.frame import (
        FLAG_COMPRESSED, TYPE_NOTIFY, TYPE_RESPONSE,
        build_frame, build_size,
    )
except ImportError:
    print("\n  +--------------------------------------------------------+")
    print("  |  LUMEN Python package required.                        |")
    print("  |  Install:  pip install -e implementations/python       |")
    print("  +--------------------------------------------------------+")
    sys.exit(1)

# ── Fixture generators ───────────────────────────────────────────────────────

TOOL_TEMPLATES = [
    ("search_code", "Search for code patterns in the workspace",
     [("query", "string", "The search query or pattern"),
      ("path", "string", "Optional path to scope the search"),
      ("max_results", "integer", "Maximum number of results")]),
    ("read_file", "Read the contents of a file from the filesystem",
     [("uri", "string", "URI of the file to read"),
      ("start_line", "integer", "Starting line number (1-based)"),
      ("end_line", "integer", "Ending line number (inclusive)")]),
    ("write_file", "Write content to a file",
     [("path", "string", "Absolute path to the target file"),
      ("content", "string", "Content to write to the file"),
      ("overwrite", "boolean", "Whether to overwrite existing files")]),
    ("execute_command", "Execute a shell command in the terminal",
     [("command", "string", "The command to execute"),
      ("working_dir", "string", "Working directory for execution"),
      ("timeout_ms", "integer", "Timeout in milliseconds")]),
    ("list_directory", "List contents of a directory",
     [("path", "string", "Absolute path to the directory"),
      ("pattern", "string", "Glob pattern for filtering"),
      ("recursive", "boolean", "Whether to list recursively")]),
    ("get_diagnostics", "Retrieve compiler and linter errors",
     [("file_path", "string", "Optional file path to scope diagnostics"),
      ("severity", "string", "Filter by severity: error, warning, info")]),
    ("semantic_search", "Search codebase using natural language",
     [("query", "string", "Natural language description of what to find"),
      ("top_k", "integer", "Number of results to return"),
      ("include_comments", "boolean", "Whether to include comments")]),
    ("manage_memory", "Manage persistent memory across sessions",
     [("operation", "string", "Memory operation: view, create, update, delete"),
      ("path", "string", "Path within the memory namespace"),
      ("content", "string", "Content for create/update operations")]),
    ("fetch_webpage", "Fetch and extract content from web pages",
     [("urls", "array", "Array of URLs to fetch"),
      ("query", "string", "Information to extract from the pages")]),
    ("create_rule", "Create or update a project rule or coding standard",
     [("name", "string", "Name of the rule"),
      ("description", "string", "What the rule enforces"),
      ("severity", "string", "Rule severity: error, warning, info, hint"),
      ("pattern", "string", "Regex pattern for the rule")]),
]

CODE_SNIPPETS = [
    "pub async fn handle_request(&self, req: Request) -> Result<Response, Error> {",
    "    let start = std::time::Instant::now();",
    "    let payload = self.decode_frame(&req.payload)?;",
    "    match req.frame_type {",
    "        FrameType::Request => self.handle_rpc(payload).await,",
    '        FrameType::Notify => { self.handle_notify(payload).await; Ok(()) },',
    "        FrameType::Heartbeat => Ok(()),",
    "        _ => Err(Error::UnknownFrameType),",
    "    }",
    "}",
    "",
    "async fn handle_rpc(&self, payload: Value) -> Result<Value, Error> {",
    '    let method = payload.get("method").and_then(|v| v.as_str())',
    "        .ok_or(Error::MissingMethod)?;",
    '    let params = payload.get("params").cloned()',
    "        .unwrap_or(Value::Null);",
    "    match method {",
    '        "tools/list" => self.list_tools().await,',
    '        "tools/call" => self.call_tool(params).await,',
    '        "resources/list" => self.list_resources().await,',
    '        "prompts/list" => self.list_prompts().await,',
    "        _ => Err(Error::UnknownMethod(method.to_string())),",
    "    }",
    "}",
]

TOKENS = [
    "The", " quick", " brown", " fox", " jumps", " over", " the", " lazy",
    " dog", ".", " Pack", " my", " box", " with", " five", " dozen",
    " liquor", " jugs", ".", " How", " vexingly", " quick", " daft",
    " zebras", " jump", "!", " Sphinx", " of", " black", " quartz",
    ",", " judge", " my", " vow", ".", " The", " five", " boxing",
    " wizards", " jump", " quickly", ".", " Mr.", " Jock",
    ",", " TV", " quiz", " PhD", ",", " bags", " few", " lynx",
    ".", " Waltz", ",", " bad", " nymph", ",", " for", " quick",
    " jigs", " vex", ".", " Glib", " jocks", " quiz", " nymph",
    " to", " vex", " dwarf", ".", " Jack", " fox", " bid", " zilch",
    " TV", " quiz", " PhD", ",", " bags", " few", " lynx", ".",
]


def generate_tools(n: int) -> list[dict]:
    tools = []
    for i in range(n):
        name, desc, props = TOOL_TEMPLATES[i % len(TOOL_TEMPLATES)]
        variant = i // len(TOOL_TEMPLATES)
        tool_name = f"{name}_{variant}" if variant > 0 else name
        properties = {
            pname: {"type": ptype, "description": pdesc}
            for pname, ptype, pdesc in props
        }
        tools.append({
            "name": tool_name,
            "description": f"{desc} (variant {variant + 1})",
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": [props[0][0]],
            },
        })
    return tools


def build_tools_list_response(tools: list[dict]) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"tools": tools}}


def generate_source_code(language: str, size_kb: int) -> str:
    code = f"// {language} file: generated for benchmark\n"
    i = 0
    while len(code.encode("utf-8")) < size_kb * 1024:
        code += CODE_SNIPPETS[i % len(CODE_SNIPPETS)] + "\n"
        i += 1
    return code


def build_file_context_payload(files: list[dict]) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {
            "resources": [
                {
                    "uri": f["uri"],
                    "mimeType": "text/plain",
                    "text": f["content"],
                    "language": f.get("language", "plaintext"),
                    "filename": f["filename"],
                }
                for f in files
            ]
        },
    }


def build_token_stream_messages(tokens: list[str]) -> list[dict]:
    return [
        {
            "jsonrpc": "2.0",
            "method": "notifications/token",
            "params": {"id": 3, "token": tok.strip(), "index": i},
        }
        for i, tok in enumerate(tokens)
    ]


def build_multi_agent_requests(n_agents: int, n_reqs: int) -> list[dict]:
    requests = []
    for a in range(n_agents):
        for r in range(n_reqs):
            tool_idx = (a * n_reqs + r) % len(TOOL_TEMPLATES)
            name, _, props = TOOL_TEMPLATES[tool_idx]
            requests.append({
                "jsonrpc": "2.0",
                "id": a * 1000 + r,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {p[0]: f"value_{a}_{r}" for p in props},
                    "agent": f"agent-{a}",
                },
            })
    return requests


def build_heartbeat() -> dict:
    return {"jsonrpc": "2.0", "method": "ping", "params": {}}

# ── Measurement engine ──────────────────────────────────────────────────────

@dataclass
class ScenarioResult:
    name: str
    label: str
    json_wire_bytes: int
    lumen_wire_bytes: int
    savings_pct: float = 0.0

    def __post_init__(self):
        if self.json_wire_bytes > 0:
            self.savings_pct = (
                (self.json_wire_bytes - self.lumen_wire_bytes)
                / self.json_wire_bytes * 100
            )


def measure_json_path(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def measure_lumen_path(payload: dict,
                       frame_type: int = TYPE_RESPONSE,
                       flags: int = FLAG_COMPRESSED) -> int:
    """LUMEN path: compress + frame, return wire size in bytes."""
    compressed = compress_value(payload)
    # build_size returns total wire bytes: Hyb128 header + type + flags + payload
    return build_size(payload_len=len(compressed))


# ── Scenario runner ─────────────────────────────────────────────────────────

def run_all_scenarios() -> list[ScenarioResult]:
    results = []

    # S1: tools/list with 100 tools
    tools100 = generate_tools(100)
    payload100 = build_tools_list_response(tools100)
    results.append(ScenarioResult(
        name="tools/list",
        label="tools/list (100 tools)",
        json_wire_bytes=measure_json_path(payload100),
        lumen_wire_bytes=measure_lumen_path(payload100),
    ))

    # S1b: tools/list with 500 tools
    tools500 = generate_tools(500)
    payload500 = build_tools_list_response(tools500)
    results.append(ScenarioResult(
        name="tools/list (large)",
        label="tools/list (500 tools)",
        json_wire_bytes=measure_json_path(payload500),
        lumen_wire_bytes=measure_lumen_path(payload500),
    ))

    # S2: file_context
    files = []
    languages = ["rust", "typescript", "python"]
    for i in range(50):
        lang = languages[i % 3]
        files.append({
            "uri": f"file:///project/src/module_{i}.ts",
            "filename": f"module_{i}.ts",
            "content": generate_source_code(lang, 100),
            "language": lang,
        })
    fc_payload = build_file_context_payload(files)
    results.append(ScenarioResult(
        name="file_context",
        label="file_context (50 files x 100KB)",
        json_wire_bytes=measure_json_path(fc_payload),
        lumen_wire_bytes=measure_lumen_path(fc_payload),
    ))

    # S3: token_stream
    n_tokens = 10000
    tokens = (TOKENS * math.ceil(n_tokens / len(TOKENS)))[:n_tokens]
    ts_msgs = build_token_stream_messages(tokens)
    jw_ts = sum(measure_json_path(m) for m in ts_msgs)
    lw_ts = sum(build_size(payload_len=len(compress_value(m))) for m in ts_msgs)
    results.append(ScenarioResult(
        name="token_stream",
        label=f"token_stream ({n_tokens // 1000}K tokens)",
        json_wire_bytes=jw_ts,
        lumen_wire_bytes=lw_ts,
    ))

    # S4: multi_agent
    ma_reqs = build_multi_agent_requests(10, 100)
    jw_ma = sum(measure_json_path(r) for r in ma_reqs)
    lw_ma = sum(build_size(payload_len=len(compress_value(r))) for r in ma_reqs)
    results.append(ScenarioResult(
        name="multi_agent",
        label="multi_agent (10 agents x 100 reqs)",
        json_wire_bytes=jw_ma,
        lumen_wire_bytes=lw_ma,
    ))

    # S5: heartbeat
    hb = build_heartbeat()
    results.append(ScenarioResult(
        name="heartbeat",
        label="heartbeat (single ping)",
        json_wire_bytes=measure_json_path(hb),
        lumen_wire_bytes=measure_lumen_path(hb, TYPE_NOTIFY, 0),
    ))

    return results

# ── Output formatting ───────────────────────────────────────────────────────

def fmt_bytes(b: int) -> str:
    if b >= 1024 * 1024:
        return f"{b / (1024 * 1024):.2f} MB"
    if b >= 1024:
        return f"{b / 1024:.1f} KB"
    return f"{b} B"


def fmt_pct(pct: float) -> str:
    bar = " >>>" if pct >= 90 else " >>" if pct >= 80 else " >" if pct >= 60 else ""
    return f"{pct:.1f}%{bar}"


def print_header() -> None:
    print()
    print("  " + "\u2550" * 78)
    print("  \u2551" + f"{"LUMEN COST CALCULATOR  -  v1.0":^76}" + "\u2551")
    print("  \u2551" + f"{"How much is JSON-RPC costing your infrastructure?":^76}" + "\u2551")
    print("  " + "\u2550" * 78)
    print()


def print_scenario_table(results: list[ScenarioResult]) -> None:
    print()
    print("  " + "\u2550" * 82)
    print(f"  \u2551 {"LUMEN Protocol  -  Wire Size Comparison":^78} \u2551")
    print("  " + "\u2550" * 82)
    print(f"  \u2551 {"MCP Scenario":<38} {"JSON-RPC":>12} {"LUMEN":>12} {"Savings":>12} \u2551")
    print("  \u2551 " + "-" * 76 + " \u2551")
    total_json = 0
    total_lumen = 0
    for r in results:
        json_str = fmt_bytes(r.json_wire_bytes)
        lumen_str = fmt_bytes(r.lumen_wire_bytes)
        pct = fmt_pct(r.savings_pct)
        print(f"  \u2551 {r.label:<38} {json_str:>12} {lumen_str:>12} {pct:>12} \u2551")
        total_json += r.json_wire_bytes
        total_lumen += r.lumen_wire_bytes
    print("  \u2551 " + "-" * 76 + " \u2551")
    avg_savings = ((total_json - total_lumen) / total_json * 100) if total_json > 0 else 0
    print(f"  \u2551 {"AGGREGATE":<38} {fmt_bytes(total_json):>12} {fmt_bytes(total_lumen):>12} {fmt_pct(avg_savings):>12} \u2551")
    print("  " + "\u2550" * 82)
    print()
    return avg_savings


def print_cost_projection(avg_savings_pct: float, monthly_calls: int,
                          avg_json_bytes: float, avg_egress_per_gb: float) -> None:
    savings_ratio = avg_savings_pct / 100.0
    monthly_json_gb = (monthly_calls * avg_json_bytes) / (1024**3)
    monthly_lumen_gb = monthly_json_gb * (1 - savings_ratio)
    monthly_json_cost = monthly_json_gb * avg_egress_per_gb
    monthly_lumen_cost = monthly_lumen_gb * avg_egress_per_gb

    print("\n  " + "\u2550" * 78)
    print(f"  \u2551 {"LUMEN Cost Projection  -  Annual Savings":^76} \u2551")
    print("  " + "\u2550" * 78)
    print(f"  \u2551 {"Assumptions:":<76} \u2551")
    print(f"  \u2551   Monthly MCP calls:      {monthly_calls:>12,}                          \u2551")
    print(f"  \u2551   Average JSON payload:   {avg_json_bytes / 1024:.1f} KB                            \u2551")
    print(f"  \u2551   Average wire savings:   {avg_savings_pct:.1f}%                            \u2551")
    print(f"  \u2551   Egress cost:            ${avg_egress_per_gb:.2f}/GB  (AWS/GCP standard)      \u2551")
    print("  \u2551" + " " * 76 + "\u2551")
    print(f"  \u2551   Monthly egress (JSON):  {monthly_json_gb:>8.1f} GB  ->  ${monthly_json_cost:>8.2f}              \u2551")
    print(f"  \u2551   Monthly egress (LUMEN): {monthly_lumen_gb:>8.1f} GB  ->  ${monthly_lumen_cost:>8.2f}              \u2551")
    print("  \u2551" + " " * 76 + "\u2551")
    monthly_savings = monthly_json_cost - monthly_lumen_cost
    annual_savings = monthly_savings * 12
    print(f"  \u2551   Monthly savings:        ${monthly_savings:>8.2f}                         \u2551")
    print(f"  \u2551   Annual savings:         ${annual_savings:>8.2f}  ... per server           \u2551")
    print("  \u2551" + " " * 76 + "\u2551")
    for n in [50, 200, 1000]:
        print(f"  \u2551   With {n:>4} servers:        ${annual_savings * n:>10,.0f}/year                     \u2551")
    print("  " + "\u2550" * 78)
    print()


def export_csv(results: list[ScenarioResult], filepath: str) -> None:
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["scenario", "json_wire_bytes", "lumen_wire_bytes", "savings_pct"])
        for r in results:
            writer.writerow([r.name, r.json_wire_bytes, r.lumen_wire_bytes, f"{r.savings_pct:.1f}"])
    print(f"  CSV exported to: {filepath}")


# ── Main ─────────────────────────────────────────────────────────────────────

def parse_count(val: str) -> int:
    val = val.strip().upper()
    if val.endswith("K"):
        return int(float(val[:-1]) * 1_000)
    if val.endswith("M"):
        return int(float(val[:-1]) * 1_000_000)
    if val.endswith("B"):
        return int(float(val[:-1]) * 1_000_000_000)
    return int(val)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LUMEN Cost Calculator — project infrastructure savings from switching to LUMEN"
    )
    parser.add_argument("--monthly-calls", type=str, default="10M",
                        help="Monthly MCP call volume (e.g. 10M, 500K, 1B)")
    parser.add_argument("--egress-cost", type=float, default=0.09,
                        help="Egress cost per GB in USD (default: 0.09)")
    parser.add_argument("--csv", type=str, default=None,
                        help="Export results to CSV file")
    args = parser.parse_args()

    monthly_calls = parse_count(args.monthly_calls)
    egress_cost = args.egress_cost

    print_header()
    print("  Running benchmarks on realistic MCP payloads...")
    results = run_all_scenarios()
    avg_savings = print_scenario_table(results)

    # Average JSON payload size for cost projection
    all_json_sizes = [r.json_wire_bytes for r in results]
    avg_json = sum(all_json_sizes) / len(all_json_sizes)

    print_cost_projection(avg_savings, monthly_calls, avg_json, egress_cost)

    if args.csv:
        export_csv(results, args.csv)


if __name__ == "__main__":
    main()
