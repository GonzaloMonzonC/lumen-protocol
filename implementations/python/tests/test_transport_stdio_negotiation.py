"""Regression test: LUMEN stdio negotiation on Windows pipes.

Covers the deadlock reintroduced by commit 8108831 ("reader thread (64KB
chunks)"): on Windows pipes BufferedReader.read(N) blocks until N bytes or
EOF, so the small PROBE_ACK (~50B) never satisfied the 64 KiB read and the
reader thread deadlocked forever (every MCP call hung until timeout).

The fix uses read1() which returns as soon as ANY data is available,
matching the TypeScript stream semantics this transport was ported from.

Without the fix: use_lumen stays False (probe timeout) and no response to
initialize ever arrives. With the fix: negotiation completes in ~0.2s and
the initialize round-trip returns serverInfo lumen-thinking-native.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from lumen.transport import LumenStdioTransport  # noqa: E402

_THINKING = pathlib.Path(__file__).resolve().parent.parent.parent / "mcp-servers" / "thinking"
SERVER = str(_THINKING / "server_native.py")
CWD = str(_THINKING)


def test_stdio_lumen_negotiation_and_roundtrip() -> None:
    async def run() -> tuple[bool, list[dict]]:
        t = LumenStdioTransport(
            command=sys.executable,
            args=[SERVER],
            cwd=CWD,
            probe_timeout_ms=5000,
        )
        msgs: list[dict] = []
        t.onmessage = msgs.append
        await t.start()
        use_lumen = t._use_lumen
        if use_lumen:
            await t.send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "transport-regression-test", "version": "1.0"},
                },
            })
            await asyncio.sleep(2)
        await t.close()
        return use_lumen, msgs

    use_lumen, msgs = asyncio.run(run())

    assert use_lumen is True, "LUMEN negotiation failed — PROBE_ACK never processed"
    assert len(msgs) == 1, f"expected 1 response, got {len(msgs)}: {msgs}"
    result = msgs[0].get("result", {})
    assert result.get("serverInfo", {}).get("name") == "lumen-thinking-native"
