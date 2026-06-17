"""
LUMEN MCP Tool Evaluation Framework — Objective, repeatable, quantitative.
Metrics: correctness, error handling, security, latency, coverage.
"""

from __future__ import annotations
import json, sys, os, time, subprocess, tempfile, shutil
from typing import Callable, Any

class MCPTestRunner:
    """Unified test runner for MCP servers. Tracks metrics per tool."""

    def __init__(self, server_name: str):
        self.server_name = server_name
        self.results: list[dict] = []
        self._started = time.perf_counter()

    def test(self, tool: str, category: str, check_fn: Callable[[], bool],
             detail: str = "") -> dict:
        """Run a single test, recording timing and result."""
        t0 = time.perf_counter()
        try:
            ok = check_fn()
            latency = time.perf_counter() - t0
            self.results.append({
                "tool": tool, "category": category, "passed": ok,
                "latency_ms": round(latency * 1000, 2), "detail": detail
            })
            return {"ok": ok, "latency": latency * 1000}
        except Exception as e:
            latency = time.perf_counter() - t0
            self.results.append({
                "tool": tool, "category": category, "passed": False,
                "latency_ms": round(latency * 1000, 2),
                "error": str(e), "detail": detail
            })
            return {"ok": False, "latency": latency * 1000, "error": str(e)}

    def report(self) -> str:
        """Generate scored report grouped by tool and category."""
        elapsed = time.perf_counter() - self._started

        # Group by tool
        by_tool: dict[str, list[dict]] = {}
        for r in self.results:
            by_tool.setdefault(r["tool"], []).append(r)

        lines = []
        lines.append(f"\n{'═'*65}")
        lines.append(f"║  ◆  {self.server_name} — TOOL EVALUATION REPORT  ◆")
        lines.append(f"{'═'*65}")

        total_passed = sum(1 for r in self.results if r["passed"])
        total_tests = len(self.results)

        for tool, tests in sorted(by_tool.items()):
            passed = sum(1 for t in tests if t["passed"])
            total = len(tests)
            pct = 100 * passed / total if total else 0
            latencies = [t["latency_ms"] for t in tests if "latency_ms" in t]
            avg_lat = sum(latencies) / len(latencies) if latencies else 0
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))

            lines.append(f"\n  {tool}")
            lines.append(f"    {bar} {pct:.0f}% ({passed}/{total}) · {avg_lat:.1f}ms avg")
            for t in tests:
                icon = "✅" if t["passed"] else "❌"
                cat = t.get("category", "")
                detail = t.get("detail", "")
                err = t.get("error", "")
                lat = t.get("latency_ms", 0)
                suffix = f" [{err}]" if err else f" [{detail}]" if detail else ""
                lines.append(f"    {icon} {cat:<20} {lat:>6.1f}ms{suffix}")

        lines.append(f"\n{'─'*65}")
        lines.append(f"  OVERALL: {total_passed}/{total_tests} ({100*total_passed/max(total_tests,1):.0f}%) in {elapsed:.1f}s")
        if total_passed == total_tests:
            lines.append(f"  🏆 ALL TESTS PASSED — PRODUCTION READY")
        else:
            failed = total_tests - total_passed
            lines.append(f"  ⚠️  {failed} FAILURES")
        lines.append(f"{'═'*65}\n")
        return "\n".join(lines)
