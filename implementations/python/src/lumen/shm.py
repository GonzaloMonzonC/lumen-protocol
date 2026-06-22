"""
LUMEN Level 2 — Zero-Copy Shared Memory Transport (Python)

Two unidirectional lock-free SPSC ring buffers in a single mmap'd region.
Header (128 bytes) matches the Rust implementation byte-for-byte.

Ring A: Client → Server   |   Ring B: Server → Client

Usage (server side):
    region = ShmRegion.create("lumen-shm-1234", size=512*1024)
    region.init_header()
    write_ring = region.ring_buffer(RingSide.B)  # server writes to B
    read_ring = region.ring_buffer(RingSide.A)    # server reads from A
    transport = ShmTransport(write_ring, read_ring)

Usage (client side — Hermes):
    region = ShmRegion.open("lumen-shm-1234", size=512*1024)
    write_ring = region.ring_buffer(RingSide.A)  # client writes to A
    read_ring = region.ring_buffer(RingSide.B)    # client reads from B
    transport = ShmTransport(write_ring, read_ring)
"""

from __future__ import annotations

import mmap
import os
import struct
import sys
import time
import ctypes
from enum import Enum
from typing import Optional


# ── Constants (must match Rust shm.rs) ──────────────────────────────────

SHM_MAGIC: int = 0x4C554D45       # "LUME"
SHM_VERSION: int = 1
DEFAULT_REGION_SIZE: int = 512 * 1024  # 512 KiB
HEADER_SIZE: int = 128

MAX_SPIN: int = 10_000_000      # 10M — was 50M. Reduced since async saves reduce server latency
YIELD_INTERVAL: int = 50        # yield every 50 spins (was 100)
MAX_FRAME_SIZE: int = 16 * 1024 * 1024  # 16 MiB


class RingSide(Enum):
    A = 0  # Client → Server
    B = 1  # Server → Client


# ── Header offsets (must match Rust #[repr(C)] ShmHeader) ──────────────

OFF_MAGIC       = 0    # u32
OFF_VERSION     = 4    # u32
OFF_DATA_OFFSET = 8    # u64
OFF_DATA_LEN    = 16   # u64
OFF_MID         = 24   # u64
OFF_WRITE_A     = 32   # AtomicU64
OFF_READ_A      = 40   # AtomicU64
OFF_WRITE_B     = 48   # AtomicU64
OFF_READ_B      = 56   # AtomicU64


class ShmRegion:
    """A mapped shared memory region with two ring buffers."""

    def __init__(
        self,
        mm: mmap.mmap,
        size: int,
        tag: Optional[str] = None,
        is_owner: bool = False,
    ):
        self._mm = mm
        self._size = size
        self._tag = tag
        self._is_owner = is_owner  # True = server (creates + cleans up)

    @classmethod
    def create(cls, name: str, size: int = DEFAULT_REGION_SIZE) -> "ShmRegion":
        """Create a new shared memory region (server side)."""
        if sys.platform == "win32":
            # Windows: mmap with tagname creates named shared memory
            mm = mmap.mmap(-1, size, tagname=name)
        else:
            # Unix: create file in /dev/shm, mmap it
            shm_path = f"/dev/shm/{name}"
            fd = os.open(shm_path, os.O_CREAT | os.O_RDWR | os.O_EXCL, 0o600)
            try:
                os.ftruncate(fd, size)
                mm = mmap.mmap(fd, size, flags=mmap.MAP_SHARED)
            finally:
                os.close(fd)  # fd no longer needed after mmap

        return cls(mm, size, tag=name, is_owner=True)

    @classmethod
    def open(cls, name: str, size: int = DEFAULT_REGION_SIZE) -> "ShmRegion":
        """Open an existing shared memory region (client side)."""
        if sys.platform == "win32":
            mm = mmap.mmap(-1, size, tagname=name)
        else:
            shm_path = f"/dev/shm/{name}"
            fd = os.open(shm_path, os.O_RDWR)
            try:
                mm = mmap.mmap(fd, size, flags=mmap.MAP_SHARED)
            finally:
                os.close(fd)

        return cls(mm, size, tag=name, is_owner=False)

    def init_header(self) -> None:
        """Initialize the header of a freshly-created region."""
        data_len = self._size - HEADER_SIZE
        mid = HEADER_SIZE + data_len // 2

        self._write_u32(OFF_MAGIC, SHM_MAGIC)
        self._write_u32(OFF_VERSION, SHM_VERSION)
        self._write_u64(OFF_DATA_OFFSET, HEADER_SIZE)
        self._write_u64(OFF_DATA_LEN, data_len)
        self._write_u64(OFF_MID, mid)
        self._write_u64(OFF_WRITE_A, 0)
        self._write_u64(OFF_READ_A, 0)
        self._write_u64(OFF_WRITE_B, 0)
        self._write_u64(OFF_READ_B, 0)

        # Zero out data region
        self._mm.seek(HEADER_SIZE)
        self._mm.write(b'\x00' * data_len)

    def validate(self) -> bool:
        """Check header magic and version."""
        return (
            self._read_u32(OFF_MAGIC) == SHM_MAGIC
            and self._read_u32(OFF_VERSION) == SHM_VERSION
        )

    def ring_buffer(self, side: RingSide) -> "ShmRingBuffer":
        """Create a ring buffer for the given side."""
        return ShmRingBuffer(self, side)

    def close(self) -> None:
        """Unmap and clean up."""
        self._mm.close()
        if self._is_owner and self._tag:
            if sys.platform == "win32":
                pass  # Windows auto-cleans named mmaps on last close
            else:
                try:
                    os.unlink(f"/dev/shm/{self._tag}")
                except OSError:
                    pass

    @property
    def size(self) -> int:
        return self._size

    # ── Low-level read/write helpers ──

    def _read_u32(self, offset: int) -> int:
        self._mm.seek(offset)
        return struct.unpack('<I', self._mm.read(4))[0]

    def _write_u32(self, offset: int, value: int) -> None:
        self._mm.seek(offset)
        self._mm.write(struct.pack('<I', value))

    def _read_u64(self, offset: int) -> int:
        self._mm.seek(offset)
        return struct.unpack('<Q', self._mm.read(8))[0]

    def _write_u64(self, offset: int, value: int) -> None:
        self._mm.seek(offset)
        self._mm.write(struct.pack('<Q', value))

    def _read_bytes(self, offset: int, n: int) -> bytes:
        self._mm.seek(offset)
        return self._mm.read(n)

    def _write_bytes(self, offset: int, data: bytes) -> None:
        self._mm.seek(offset)
        self._mm.write(data)

    # Allow ShmRingBuffer to access internals
    def _get_mmap(self) -> mmap.mmap:
        return self._mm

    @property
    def data_offset(self) -> int:
        return HEADER_SIZE

    @property
    def data_len(self) -> int:
        return self._size - HEADER_SIZE


class ShmRingBuffer:
    """Lock-free SPSC ring buffer backed by shared memory."""

    def __init__(self, region: ShmRegion, side: RingSide):
        self._region = region
        self._side = side
        self._mm = region._get_mmap()

        # Map cursor offsets based on side
        if side == RingSide.A:
            self._off_write = OFF_WRITE_A
            self._off_read = OFF_READ_A
            self._rng_start = OFF_DATA_OFFSET
            self._rng_end = OFF_MID
        else:  # B
            self._off_write = OFF_WRITE_B
            self._off_read = OFF_READ_B
            self._rng_start = OFF_MID
            self._rng_end = OFF_DATA_OFFSET

    # ── Cursor access ──

    @property
    def write_cursor(self) -> int:
        return self._region._read_u64(self._off_write)

    @write_cursor.setter
    def write_cursor(self, value: int) -> None:
        self._region._write_u64(self._off_write, value)

    @property
    def read_cursor(self) -> int:
        return self._region._read_u64(self._off_read)

    @read_cursor.setter
    def read_cursor(self, value: int) -> None:
        self._region._write_u64(self._off_read, value)

    @property
    def ring_start(self) -> int:
        return self._region._read_u64(self._rng_start)

    @property
    def ring_end(self) -> int:
        """Ring end. For Ring A = mid; for Ring B = data_offset + data_len."""
        if self._side == RingSide.A:
            return self._region._read_u64(self._rng_end)
        else:
            # Ring B: end = data_offset + data_len
            return (
                self._region._read_u64(OFF_DATA_OFFSET)
                + self._region._read_u64(OFF_DATA_LEN)
            )

    @property
    def ring_len(self) -> int:
        return self.ring_end - self.ring_start

    # ── Write ──────────────────────────────────────────────────────────

    def write(self, data: bytes) -> int:
        """Write data to the ring buffer. Spins if full. Returns bytes written."""
        start = self.ring_start
        length = self.ring_len
        cap = length - 1  # one byte reserved to distinguish full/empty
        written = 0
        spins = 0
        total = len(data)

        while written < total:
            w = self.write_cursor
            r = self.read_cursor
            used = w - r if w >= r else w + length - r
            avail = cap - used

            if avail <= 0:
                spins += 1
                if spins >= MAX_SPIN:
                    raise TimeoutError("SHM ring buffer timeout: write peer appears dead")
                if spins % YIELD_INTERVAL == 0:
                    time.sleep(0)
                continue

            spins = 0
            n = min(total - written, avail)
            wabs = start + (w % length)

            # Write, handling wrap-around
            c1 = min(n, start + length - wabs)
            self._region._write_bytes(wabs, data[written:written + c1])
            if c1 < n:
                c2 = n - c1
                self._region._write_bytes(start, data[written + c1:written + c1 + c2])

            nw = w + n
            if nw >= length:
                nw -= length
            self.write_cursor = nw
            written += n

        return written

    def write_frame(self, data: bytes) -> int:
        """Write a length-prefixed frame (4-byte LE length + data)."""
        frame = struct.pack('<I', len(data)) + data
        return self.write(frame)

    # ── Read ───────────────────────────────────────────────────────────

    def read(self, buf: bytearray) -> int:
        """Read available data into buf. Returns bytes read (0 if empty)."""
        start = self.ring_start
        length = self.ring_len
        w = self.write_cursor
        r = self.read_cursor

        if w == r:
            return 0

        avail = w - r if w > r else w + length - r
        n = min(avail, len(buf))
        rabs = start + (r % length)

        c1 = min(n, start + length - rabs)
        buf[:c1] = self._region._read_bytes(rabs, c1)
        if c1 < n:
            c2 = n - c1
            buf[c1:c1 + c2] = self._region._read_bytes(start, c2)

        nr = r + n
        if nr >= length:
            nr -= length
        self.read_cursor = nr
        return n

    def read_frame(self) -> Optional[bytes]:
        """Read a complete length-prefixed frame. Returns None on timeout."""
        # Read 4-byte length header with retry
        lb = bytearray(4)
        hdr_read = 0
        hdr_spins = 0
        while hdr_read < 4:
            buf = bytearray(4 - hdr_read)
            n = self.read(buf)
            if n > 0:
                lb[hdr_read:hdr_read + n] = buf[:n]
                hdr_read += n
                hdr_spins = 0
            else:
                hdr_spins += 1
                if hdr_spins >= MAX_SPIN:
                    return None  # timeout
                if hdr_spins % YIELD_INTERVAL == 0:
                    time.sleep(0)

        flen = struct.unpack('<I', bytes(lb))[0]
        if flen > MAX_FRAME_SIZE:
            raise ValueError(
                f"Frame too large: {flen} bytes (max {MAX_FRAME_SIZE})"
            )

        # Read frame body with retry
        result = bytearray(flen)
        total = 0
        spins = 0
        while total < flen:
            buf = bytearray(flen - total)
            n = self.read(buf)
            if n == 0:
                spins += 1
                if spins >= MAX_SPIN:
                    return None  # timeout
                if spins % YIELD_INTERVAL == 0:
                    time.sleep(0)
                continue
            spins = 0
            result[total:total + n] = buf[:n]
            total += n

        return bytes(result)

    def available(self) -> int:
        """Bytes available for reading (non-blocking)."""
        w = self.write_cursor
        r = self.read_cursor
        length = self.ring_len
        return w - r if w >= r else w + length - r


class ShmTransport:
    """Zero-copy shared memory transport (LTA Level 2).

    Uses two ring buffers for full-duplex communication.
    Pairs with LumenStdioTransport for control channel.
    """

    def __init__(self, write_ring: ShmRingBuffer, read_ring: ShmRingBuffer):
        self.write_ring = write_ring
        self.read_ring = read_ring
        self._read_buf = bytearray()
        self._read_pos = 0

    def send_frame(self, data: bytes) -> None:
        """Send a LUMEN frame through the write ring."""
        self.write_ring.write_frame(data)

    def recv_frame(self) -> Optional[bytes]:
        """Receive a LUMEN frame from the read ring. None on timeout."""
        return self.read_ring.read_frame()

    def has_data(self) -> bool:
        """Check if data is available without blocking."""
        return self._read_pos < len(self._read_buf) or self.read_ring.available() > 0

    def close(self) -> None:
        """Close transport (no-op for shm — caller must close ShmRegion)."""
        pass
