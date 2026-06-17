"""
FrameAssembler — streaming frame reassembler with amortized O(1) append.

Accumulates raw bytes from a stream (stdio, TCP, WebSocket) and yields
complete LUMEN frames as they become available. Avoids the O(n²) trap of
``del buf[:consumed]`` by tracking a read offset and compacting lazily.

Ported from TypeScript ``src/frame-assembler.ts``.
"""

from __future__ import annotations

from .frame import Frame, parse_frame, ParseComplete, ParseIncomplete

# Default maximum frame size (4 MiB) — prevents OOM from malicious peers.
DEFAULT_MAX_FRAME = 4 * 1024 * 1024

# When the read offset exceeds this threshold, compact the buffer by
# shifting remaining bytes to the front. Balancing memory vs copy cost.
COMPACT_THRESHOLD = 64 * 1024  # 64 KiB


class FrameAssembler:
    """Reassembles LUMEN frames from a byte stream.

    Usage::

        assembler = FrameAssembler(max_frame=1_000_000)
        for chunk in stream:
            for frame in assembler.push(chunk):
                handle(frame)
    """

    __slots__ = ("_buf", "_offset", "_max_frame")

    def __init__(self, max_frame: int = DEFAULT_MAX_FRAME) -> None:
        """
        Args:
            max_frame: Maximum allowed frame size in bytes (default 4 MiB).
        """
        self._buf = bytearray()
        self._offset = 0
        self._max_frame = max_frame

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def pending(self) -> int:
        """Number of unparsed bytes in the buffer (excluding consumed prefix)."""
        return len(self._buf) - self._offset

    def __len__(self) -> int:
        return self.pending

    # ── Push ────────────────────────────────────────────────────────────

    def push(self, chunk: bytes | bytearray | memoryview) -> list[Frame]:
        """Feed a raw byte chunk into the assembler.

        Returns a list of complete frames parsed from the accumulated buffer.
        Incomplete data is retained for the next call.

        Raises:
            BufferError: if the accumulated buffer exceeds ``max_frame``.
        """
        # Fast path: if the buffer is mostly consumed, compact first so
        # the incoming chunk can be appended at the tail without wasting
        # space in the consumed prefix region.
        if self._offset >= COMPACT_THRESHOLD:
            self._compact()

        new_pending = self.pending + len(chunk)
        if new_pending > self._max_frame:
            self._buf.clear()
            self._offset = 0
            raise BufferError(
                f"FrameAssembler buffer exceeded max_frame ({self._max_frame} bytes). "
                f"Peer may be sending malformed or oversized frames."
            )

        self._buf.extend(chunk)

        frames: list[Frame] = []
        mv = memoryview(self._buf)

        while True:
            result = parse_frame(mv, self._offset)
            if isinstance(result, ParseComplete):
                frames.append(result.frame)
                self._offset += result.consumed
                continue
            break

        return frames

    # ── Housekeeping ────────────────────────────────────────────────────

    def flush(self) -> bytes:
        """Return trailing incomplete bytes and clear the buffer."""
        data = bytes(self._buf[self._offset:])
        self._buf.clear()
        self._offset = 0
        return data

    def reset(self) -> None:
        """Clear the buffer, discarding any partial frame."""
        self._buf.clear()
        self._offset = 0

    # ── Internal ────────────────────────────────────────────────────────

    def _compact(self) -> None:
        """Shift unparsed bytes to the front of the buffer, resetting offset."""
        if self._offset > 0:
            remaining = len(self._buf) - self._offset
            self._buf[:remaining] = self._buf[self._offset:]
            del self._buf[remaining:]
            self._offset = 0
