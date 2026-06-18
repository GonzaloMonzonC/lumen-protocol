"""
Transport implementations — drop-in replacements for MCP SDK transports.

Each transport performs automatic LUMEN negotiation on ``start()``.
If the remote peer doesn't respond to the LUMEN probe within a
configurable timeout, the transport falls back to JSON-RPC transparently.

Ported from TypeScript ``src/transport.ts``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import os
import sys
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

from .compress import compress_value, decompress_value
from .frame import (
    FLAG_COMPRESSED,
    TYPE_NOTIFY,
    TYPE_PROBE_ACK,
    TYPE_REQUEST,
    TYPE_RESPONSE,
    build_frame,
    is_compressed,
)
from .frame_assembler import FrameAssembler
from .negotiation import (
    DEFAULT_PROBE_TIMEOUT_MS,
    build_probe,
    parse_ack,
)

logger = logging.getLogger(__name__)



def _flush_stdin(process: "subprocess.Popen[bytes]") -> None:
    """Cross-platform stdin flush. Windows raises OSError on pipe flush."""
    try:
        process.stdin.flush()
    except OSError:
        pass  # Windows: flushing stdin pipe may fail

# ═══ Message types ═══════════════════════════════════════════════════════════

# Matches the MCP SDK's JSONRPCMessage shape
JsonRpcMessage = dict[str, Any]
OnMessageCallback = Callable[[JsonRpcMessage], None] | None
OnErrorCallback = Callable[[Exception], None] | None
OnCloseCallback = Callable[[], None] | None


# ═══ Transport interface ═════════════════════════════════════════════════════


class Transport(ABC):
    """Minimal transport interface compatible with MCP SDK's ``Transport``."""

    @abstractmethod
    async def start(self) -> None:
        """Start the transport and perform LUMEN negotiation."""

    @abstractmethod
    async def send(self, message: JsonRpcMessage) -> None:
        """Send a JSON-RPC message to the remote peer."""

    @abstractmethod
    async def close(self) -> None:
        """Close the transport gracefully."""

    onmessage: OnMessageCallback = None
    onerror: OnErrorCallback = None
    onclose: OnCloseCallback = None


# ═══ Stdio Transport ═════════════════════════════════════════════════════════


class LumenStdioTransport(Transport):
    """Drop-in replacement for MCP SDK's ``StdioServerParameters``-based transport.

    On ``start()``, spawns the MCP server process and attempts LUMEN negotiation.
    If the server responds with a LUMEN ACK frame, all subsequent communication
    uses LUMEN binary frames. Otherwise, falls back to JSON-RPC line protocol.

    Usage::

        transport = LumenStdioTransport(
            command="python", args=["my_mcp_server.py"]
        )
        await transport.start()
        # Now use transport.send() / transport.onmessage like any MCP transport
    """

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        *,
        force_json_rpc: bool = False,
        probe_timeout_ms: float = DEFAULT_PROBE_TIMEOUT_MS,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._cwd = cwd
        self._force_json_rpc = force_json_rpc
        self._probe_timeout_ms = probe_timeout_ms / 1000.0

        self._process: subprocess.Popen[bytes] | None = None
        self._use_lumen = False
        self._assembler = FrameAssembler()
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False
        # Chunk reader: a dedicated thread pushes stdout chunks into an
        # asyncio queue to avoid O(threadpool) byte-at-a-time dispatch.
        self._chunk_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)
        self._stdout_thread: threading.Thread | None = None

        # Callbacks
        self.onmessage: OnMessageCallback = None
        self.onerror: OnErrorCallback = None
        self.onclose: OnCloseCallback = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the server process and negotiate LUMEN."""
        # On Windows, asyncio subprocess needs different setup
        kwargs: dict[str, Any] = {
            "args": [self._command, *self._args],
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": self._cwd,
        }
        if self._env:
            kwargs["env"] = {**os.environ, **self._env}

        # Use regular subprocess for simplicity; Python's asyncio subprocess
        # has quirks on Windows. We'll use a thread-based reader instead.
        self._process = subprocess.Popen(**kwargs)

        # Start the stdout reader thread (feeds chunks into async queue)
        self._start_stdout_thread()

        # Start stderr passthrough
        if self._process.stderr:
            self._stderr_task = asyncio.create_task(self._log_stderr())

        # ── LUMEN negotiation ──────────────────────────────────────────
        if not self._force_json_rpc:
            probe = build_probe()
            assert self._process.stdin
            self._process.stdin.write(probe.to_bytes())
            _flush_stdin(self._process)

            if await self._wait_for_ack():
                self._use_lumen = True
                self._reader_task = asyncio.create_task(self._read_lumen())
                return

        # ── JSON-RPC fallback ──────────────────────────────────────────
        self._reader_task = asyncio.create_task(self._read_jsonrpc())

    async def send(self, message: JsonRpcMessage) -> None:
        """Send a message to the remote peer."""
        if not self._process or not self._process.stdin:
            raise RuntimeError("Transport not started")

        if self._use_lumen:
            self._send_lumen(message)
        else:
            self._send_jsonrpc(message)

    async def close(self) -> None:
        """Close the transport and terminate the child process."""
        if self._closed:
            return
        self._closed = True

        # Close stdin FIRST so the child process exits and the reader
        # tasks (blocked on stdout/stderr.read()) can complete.
        if self._process and self._process.stdin:
            try:
                self._process.stdin.close()
            except Exception:
                pass

        for task in (self._stderr_task, self._reader_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._stderr_task = None
        self._reader_task = None

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
            self._process = None

        if self.onclose:
            self.onclose()

    # ── Send helpers ───────────────────────────────────────────────────────

    def _send_jsonrpc(self, message: JsonRpcMessage) -> None:
        assert self._process and self._process.stdin
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(line.encode("utf-8"))
        _flush_stdin(self._process)

    def _send_lumen(self, message: JsonRpcMessage) -> None:
        assert self._process and self._process.stdin
        # Determine frame type from message shape
        if "method" in message and "id" in message:
            frame_type = TYPE_REQUEST
        elif "result" in message or "error" in message:
            frame_type = TYPE_RESPONSE
        else:
            frame_type = TYPE_NOTIFY

        payload = compress_value(message)
        frame = build_frame(frame_type, FLAG_COMPRESSED, payload)
        self._process.stdin.write(frame.to_bytes())
        _flush_stdin(self._process)

    # ── Receive helpers ────────────────────────────────────────────────────

    def _start_stdout_thread(self) -> None:
        """Launch a dedicated thread that reads stdout in 64 KiB chunks.

        Chunks are pushed into ``_chunk_queue`` via the event loop so the
        async reader can consume them without per-byte threadpool dispatch.
        On EOF the thread pushes ``b""`` as a sentinel.
        """
        loop = asyncio.get_running_loop()
        stdout = self._process.stdout  # captured before thread starts

        def _run() -> None:
            try:
                while True:
                    # 64 KiB chunks — large enough to amortize syscall cost,
                    # small enough to keep latency acceptable.
                    chunk = stdout.read(65536)
                    if chunk is not None:
                        loop.call_soon_threadsafe(self._chunk_queue.put_nowait, chunk)
                    if not chunk:
                        break  # EOF
            except Exception:
                # Pipe closed or other I/O error — push sentinel so the
                # async reader can clean up.
                try:
                    loop.call_soon_threadsafe(self._chunk_queue.put_nowait, b"")
                except Exception:
                    pass

        self._stdout_thread = threading.Thread(target=_run, daemon=True)
        self._stdout_thread.start()

    async def _read_lumen(self) -> None:
        """Read binary LUMEN frames from the chunk queue (fed by reader thread)."""
        while True:
            try:
                chunk = await self._chunk_queue.get()
            except Exception as exc:
                if self.onerror:
                    self.onerror(exc)
                return

            if not chunk:
                # EOF sentinel
                if not self._closed and self.onclose:
                    self.onclose()
                return

            frames = self._assembler.push(chunk)
            for frame in frames:
                try:
                    payload = decompress_value(frame.payload) if is_compressed(frame) else json.loads(frame.payload)
                    if isinstance(payload, dict) and self.onmessage:
                        self.onmessage(payload)
                except Exception as exc:
                    if self.onerror:
                        self.onerror(exc)

    async def _read_jsonrpc(self) -> None:
        """Read JSON-RPC line-delimited messages from the chunk queue."""
        # Buffer for partial lines
        buf = b""

        while True:
            try:
                chunk = await self._chunk_queue.get()
            except Exception as exc:
                if self.onerror:
                    self.onerror(exc)
                return

            if not chunk:
                # Partial line at EOF is normal
                if buf.strip():
                    try:
                        message = json.loads(buf)
                        if self.onmessage:
                            self.onmessage(message)
                    except json.JSONDecodeError:
                        pass
                if not self._closed and self.onclose:
                    self.onclose()
                return

            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                    if self.onmessage:
                        self.onmessage(message)
                except json.JSONDecodeError:
                    pass

    async def _log_stderr(self) -> None:
        """Passthrough stderr for debugging."""
        assert self._process and self._process.stderr
        loop = asyncio.get_running_loop()

        while True:
            try:
                chunk = await loop.run_in_executor(
                    None, self._process.stderr.readline
                )
            except Exception:
                return
            if not chunk:
                return
            logger.debug("[mcp-server stderr] %s", chunk.decode("utf-8", errors="replace"))

    async def _wait_for_ack(self) -> bool:
        """Wait for a PROBE_ACK frame via the chunk queue (fed by reader thread)."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._probe_timeout_ms

        while loop.time() < deadline:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break

            try:
                chunk = await asyncio.wait_for(
                    self._chunk_queue.get(),
                    timeout=min(remaining, 0.1),
                )
            except asyncio.TimeoutError:
                continue
            except Exception:
                return False

            if not chunk:
                return False  # EOF

            frames = self._assembler.push(chunk)
            for frame in frames:
                if frame.frame_type == TYPE_PROBE_ACK:
                    try:
                        value = decompress_value(frame.payload)
                        return isinstance(value, dict) and "server_name" in value
                    except Exception:
                        return False

        return False


# ═══ WebSocket Transport ═════════════════════════════════════════════════════


class LumenWebSocketTransport(Transport):
    """WebSocket transport with LUMEN binary frames.

    Ideal for cloud gateways (Cadencia → API Gateway → MCP servers).

    Usage::

        transport = LumenWebSocketTransport("ws://localhost:8080/mcp")
        await transport.start()
    """

    def __init__(
        self,
        url: str,
        *,
        force_json_rpc: bool = False,
        probe_timeout_ms: float = DEFAULT_PROBE_TIMEOUT_MS,
        binary_frames: bool = True,
    ) -> None:
        self._url = url
        self._force_json_rpc = force_json_rpc
        self._probe_timeout_ms = probe_timeout_ms / 1000.0
        self._binary_frames = binary_frames

        self._ws: Any = None  # websockets connection
        self._use_lumen = False
        self._assembler = FrameAssembler()
        self._receiver_task: asyncio.Task[None] | None = None

        self.onmessage: OnMessageCallback = None
        self.onerror: OnErrorCallback = None
        self.onclose: OnCloseCallback = None

    async def start(self) -> None:
        """Connect WebSocket and negotiate LUMEN."""
        try:
            import websockets
        except ImportError:
            raise ImportError(
                "websockets package required for LumenWebSocketTransport. "
                "Install with: pip install websockets"
            )

        self._ws = await websockets.connect(self._url)

        # ── LUMEN negotiation ──────────────────────────────────────────
        if not self._force_json_rpc:
            probe = build_probe()
            await self._ws.send(probe.to_bytes())
            try:
                ack_data = await asyncio.wait_for(
                    self._ws.recv(), timeout=self._probe_timeout_ms
                )
            except asyncio.TimeoutError:
                pass  # fallback to JSON-RPC
            else:
                if isinstance(ack_data, bytes):
                    ack = parse_ack(ack_data)
                    if ack:
                        self._use_lumen = True

        self._receiver_task = asyncio.create_task(self._receive_ws())

    async def send(self, message: JsonRpcMessage) -> None:
        if not self._ws:
            raise RuntimeError("Transport not started")

        if self._use_lumen:
            payload = compress_value(message)
            frame = build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload)
            await self._ws.send(frame.to_bytes())
        else:
            await self._ws.send(json.dumps(message, ensure_ascii=False))

    async def close(self) -> None:
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        if self.onclose:
            self.onclose()

    async def _receive_ws(self) -> None:
        assert self._ws
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    frames = self._assembler.push(message)
                    for frame in frames:
                        try:
                            payload = (
                                decompress_value(frame.payload)
                                if is_compressed(frame)
                                else json.loads(frame.payload)
                            )
                            if isinstance(payload, dict) and self.onmessage:
                                self.onmessage(payload)
                        except Exception as exc:
                            if self.onerror:
                                self.onerror(exc)
                else:
                    try:
                        parsed = json.loads(message)
                        if self.onmessage:
                            self.onmessage(parsed)
                    except json.JSONDecodeError:
                        pass
        except Exception as exc:
            if self.onerror:
                self.onerror(exc)
        finally:
            if self.onclose:
                self.onclose()

# ── Backward compatibility ──────────────────────────────────
# Hermes Agent PR #47740 references MCPLumenTransport.
# Keep this alias until Hermes updates its import.
MCPLumenTransport = LumenStdioTransport
