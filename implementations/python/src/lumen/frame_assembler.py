"""
FrameAssembler — zero-allocation streaming frame reassembler.

Accumulates raw bytes from a stream (stdio, TCP, WebSocket) and yields
complete LUMEN frames as they become available. Designed for minimal
allocations: internal buffers are reused across calls.

Ported from TypeScript ``src/frame-assembler.ts``.
"""

from __future__ import annotations

from .frame import Frame, parse_frame, ParseComplete, ParseIncomplete


class FrameAssembler:
    """Reassembles LUMEN frames from a byte stream.

    Usage::

        assembler = FrameAssembler()
        for chunk in stream:
            for frame in assembler.push(chunk):
                handle(frame)
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def push(self, chunk: bytes | bytearray | memoryview) -> list[Frame]:
        """Feed a raw byte chunk into the assembler.

        Returns a list of complete frames parsed from the accumulated buffer.
        Incomplete data is retained for the next call.
        """
        self._buf.extend(chunk)

        frames: list[Frame] = []
        # Use memoryview once for lock-free zero-copy parsing
        mv = memoryview(self._buf)

        while True:
            result = parse_frame(mv, 0)
            if isinstance(result, ParseComplete):
                frames.append(result.frame)
                consumed = result.consumed
                del mv  # release buffer lock before modifying
                del self._buf[:consumed]
                mv = memoryview(self._buf)
                continue
            break

        return frames

    def flush(self) -> bytes:
        """Return any trailing incomplete bytes and clear the internal buffer.

        Useful on stream close to check for truncated data.
        """
        data = bytes(self._buf)
        self._buf.clear()
        return data

    def reset(self) -> None:
        """Clear the internal buffer, discarding any partial frame."""
        self._buf.clear()

    def __len__(self) -> int:
        """Number of buffered bytes waiting for completion."""
        return len(self._buf)
