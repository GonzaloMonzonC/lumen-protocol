"""
Cadencia Bridge client — spawns the Rust sidecar for high-performance file indexing.

The sidecar reads files from disk, compresses them with LUMEN, and returns
binary frames. The Python client communicates with the sidecar via a
JSON line-delimited protocol over stdin/stdout.

Ported from TypeScript ``src/cadencia.ts``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ═══ Types ════════════════════════════════════════════════════════════════════


@dataclass
class BridgeCommand:
    """A command sent to the Cadencia sidecar."""

    cmd: str
    files: list[str] = field(default_factory=list)


@dataclass
class BridgeResponse:
    """A response from the Cadencia sidecar."""

    status: str


@dataclass
class BridgeIndexResponse(BridgeResponse):
    """Response from an index command."""

    files: int = 0
    total_bytes: int = 0
    wire_bytes: int = 0
    encode_us: int = 0


@dataclass
class BridgeOptions:
    """Options for the Cadencia bridge."""

    binary_path: str
    """Path to the compiled ``cadencia-bridge`` binary."""
    cwd: str | None = None
    """Working directory for the sidecar process."""


# ═══ CadenciaBridge ═══════════════════════════════════════════════════════════


class CadenciaBridge:
    """Manages the lifecycle of the Cadencia sidecar process.

    Usage::

        bridge = CadenciaBridge(BridgeOptions(binary_path="./cadencia-bridge"))
        await bridge.start()
        result = await bridge.index(["src/main.ts", "src/utils.ts"])
        await bridge.stop()
    """

    def __init__(self, options: BridgeOptions) -> None:
        self._opts = options
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._response_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._protocol_version: str = ""

    async def start(self) -> dict[str, Any]:
        """Spawn the sidecar and perform handshake."""
        kwargs: dict[str, Any] = {
            "args": [self._opts.binary_path],
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": self._opts.cwd,
        }

        self._process = subprocess.Popen(**kwargs)
        self._reader_task = asyncio.create_task(self._read_responses())

        # Ping handshake
        result = await self._send_command("ping")
        self._protocol_version = result.get("protocol", "unknown")
        return result

    async def index(self, files: list[str]) -> BridgeIndexResponse:
        """Index a list of files through the sidecar."""
        result = await self._send_command("index", files=files)
        return BridgeIndexResponse(
            status=result.get("status", "error"),
            files=result.get("files", 0),
            total_bytes=result.get("total_bytes", 0),
            wire_bytes=result.get("wire_bytes", 0),
            encode_us=result.get("encode_us", 0),
        )

    async def stop(self) -> dict[str, Any]:
        """Graceful shutdown."""
        result = await self._send_command("stop")
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self._process:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None
        return result

    async def _send_command(self, cmd: str, files: list[str] | None = None) -> dict[str, Any]:
        """Send a command and wait for the response."""
        assert self._process and self._process.stdin

        command: dict[str, Any] = {"cmd": cmd}
        if files:
            command["files"] = files

        line = json.dumps(command) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        self._process.stdin.flush()

        try:
            return await asyncio.wait_for(self._response_queue.get(), timeout=30)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Cadencia bridge did not respond to '{cmd}' within 30s")

    async def _read_responses(self) -> None:
        """Read line-delimited JSON responses from stdout."""
        assert self._process and self._process.stdout

        loop = asyncio.get_running_loop()
        buf = b""

        while True:
            try:
                chunk = await loop.run_in_executor(
                    None, self._process.stdout.read, 4096
                )
            except Exception:
                return

            if not chunk:
                return

            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    await self._response_queue.put(msg)
                except json.JSONDecodeError:
                    logger.warning("Cadencia bridge: malformed JSON line: %s", line)
