"""
Dictionary — 128 static + 127 session IDs for key compression.

============  ==========================
Range         Purpose
============  ==========================
``0x00-0x7F`` Static dictionary (128)
``0x80-0xFE`` Session dictionary (127)
``0xFF``      Raw UTF-8 key (escape)
============  ==========================

Keys that appear in the static dictionary are encoded as 1 byte
instead of their full UTF-8 representation.

Ported from TypeScript ``src/dict.ts`` and Rust ``src/dict.rs``.
"""

from __future__ import annotations

# ═══ Reserved IDs ═════════════════════════════════════════════════════════════

STATIC_MAX: int = 0x80
SESSION_MAX: int = 0xFF
ID_RAW: int = 0xFF
TOTAL_ENTRIES: int = 255

# ═══ Static dictionary (128 entries, IDs 0x00..0x7F) ═════════════════════════

_STATIC_DICT: list[str | None] = [None] * STATIC_MAX

# Core MCP/RPC keys (0x00..0x0F)
_STATIC_DICT[0x00] = "tool"
_STATIC_DICT[0x01] = "arguments"
_STATIC_DICT[0x02] = "result"
_STATIC_DICT[0x03] = "error"
_STATIC_DICT[0x04] = "id"
_STATIC_DICT[0x05] = "name"
_STATIC_DICT[0x06] = "description"
_STATIC_DICT[0x07] = "content"
_STATIC_DICT[0x08] = "text"
_STATIC_DICT[0x09] = "type"
_STATIC_DICT[0x0A] = "method"
_STATIC_DICT[0x0B] = "params"
_STATIC_DICT[0x0C] = "jsonrpc"
_STATIC_DICT[0x0D] = "data"
_STATIC_DICT[0x0E] = "code"
_STATIC_DICT[0x0F] = "message"

# Input/output (0x10..0x1F)
_STATIC_DICT[0x10] = "input"
_STATIC_DICT[0x11] = "output"
_STATIC_DICT[0x12] = "stream"
_STATIC_DICT[0x13] = "uri"
_STATIC_DICT[0x14] = "mimeType"
_STATIC_DICT[0x15] = "encoding"
_STATIC_DICT[0x16] = "language"
_STATIC_DICT[0x17] = "title"
_STATIC_DICT[0x18] = "value"
_STATIC_DICT[0x19] = "key"
_STATIC_DICT[0x1A] = "path"
_STATIC_DICT[0x1B] = "version"
_STATIC_DICT[0x1C] = "schema"
_STATIC_DICT[0x1D] = "default"
_STATIC_DICT[0x1E] = "required"
_STATIC_DICT[0x1F] = "properties"

# Resources & tools (0x20..0x2F)
_STATIC_DICT[0x20] = "resources"
_STATIC_DICT[0x21] = "tools"
_STATIC_DICT[0x22] = "prompts"
_STATIC_DICT[0x23] = "resource"
_STATIC_DICT[0x24] = "prompt"
_STATIC_DICT[0x25] = "handler"
_STATIC_DICT[0x26] = "capabilities"
_STATIC_DICT[0x27] = "permissions"
_STATIC_DICT[0x28] = "scope"
_STATIC_DICT[0x29] = "tags"
_STATIC_DICT[0x2A] = "category"
_STATIC_DICT[0x2B] = "icon"
_STATIC_DICT[0x2C] = "metadata"
_STATIC_DICT[0x2D] = "timestamp"
_STATIC_DICT[0x2E] = "status"
_STATIC_DICT[0x2F] = "progress"

# Errors & status (0x30..0x3F)
_STATIC_DICT[0x30] = "severity"
_STATIC_DICT[0x31] = "details"
_STATIC_DICT[0x32] = "cause"
_STATIC_DICT[0x33] = "stack"
_STATIC_DICT[0x34] = "line"
_STATIC_DICT[0x35] = "column"
_STATIC_DICT[0x36] = "source"
_STATIC_DICT[0x37] = "retry"
_STATIC_DICT[0x38] = "timeout"
_STATIC_DICT[0x39] = "limit"
_STATIC_DICT[0x3A] = "offset"
_STATIC_DICT[0x3B] = "count"
_STATIC_DICT[0x3C] = "total"
_STATIC_DICT[0x3D] = "page"
_STATIC_DICT[0x3E] = "cursor"
_STATIC_DICT[0x3F] = "next"

# LLM / AI (0x40..0x4F)
_STATIC_DICT[0x40] = "model"
_STATIC_DICT[0x41] = "provider"
_STATIC_DICT[0x42] = "temperature"
_STATIC_DICT[0x43] = "max_tokens"
_STATIC_DICT[0x44] = "stop"
_STATIC_DICT[0x45] = "frequency_penalty"
_STATIC_DICT[0x46] = "presence_penalty"
_STATIC_DICT[0x47] = "top_p"
_STATIC_DICT[0x48] = "logprobs"
_STATIC_DICT[0x49] = "user"
_STATIC_DICT[0x4A] = "system"
_STATIC_DICT[0x4B] = "assistant"
_STATIC_DICT[0x4C] = "function"
_STATIC_DICT[0x4D] = "tool_calls"
_STATIC_DICT[0x4E] = "finish_reason"
_STATIC_DICT[0x4F] = "usage"

# HTTP / Web (0x50..0x5F)
_STATIC_DICT[0x50] = "url"
_STATIC_DICT[0x51] = "http_method"
_STATIC_DICT[0x52] = "headers"
_STATIC_DICT[0x53] = "body"
_STATIC_DICT[0x54] = "query"
_STATIC_DICT[0x55] = "http_status"
_STATIC_DICT[0x56] = "cookie"
_STATIC_DICT[0x57] = "session"
_STATIC_DICT[0x58] = "token"
_STATIC_DICT[0x59] = "auth"
_STATIC_DICT[0x5A] = "redirect"
_STATIC_DICT[0x5B] = "host"
_STATIC_DICT[0x5C] = "port"
_STATIC_DICT[0x5D] = "origin"
_STATIC_DICT[0x5E] = "referrer"
_STATIC_DICT[0x5F] = "agent"

# File System (0x60..0x6F)
_STATIC_DICT[0x60] = "filename"
_STATIC_DICT[0x61] = "directory"
_STATIC_DICT[0x62] = "extension"
_STATIC_DICT[0x63] = "size"
_STATIC_DICT[0x64] = "modified"
_STATIC_DICT[0x65] = "created"
_STATIC_DICT[0x66] = "accessed"
_STATIC_DICT[0x67] = "mode"
_STATIC_DICT[0x68] = "owner"
_STATIC_DICT[0x69] = "group"
_STATIC_DICT[0x6A] = "symlink"
_STATIC_DICT[0x6B] = "binary"
_STATIC_DICT[0x6C] = "base64"
_STATIC_DICT[0x6D] = "hash"
_STATIC_DICT[0x6E] = "algorithm"
_STATIC_DICT[0x6F] = "chunk"

# Operations (0x70..0x7F)
_STATIC_DICT[0x70] = "execute"
_STATIC_DICT[0x71] = "read"
_STATIC_DICT[0x72] = "write"
_STATIC_DICT[0x73] = "delete"
_STATIC_DICT[0x74] = "update"
_STATIC_DICT[0x75] = "create"
_STATIC_DICT[0x76] = "search"
_STATIC_DICT[0x77] = "list"
_STATIC_DICT[0x78] = "get"
_STATIC_DICT[0x79] = "set"
_STATIC_DICT[0x7A] = "watch"
_STATIC_DICT[0x7B] = "subscribe"
_STATIC_DICT[0x7C] = "notify"
_STATIC_DICT[0x7D] = "cancel"
_STATIC_DICT[0x7E] = "pause"
_STATIC_DICT[0x7F] = "resume"


# ═══ Reverse lookup — eagerly built O(1) dict ════════════════════════════════

_reverse_map: dict[str, int] = {}
for i in range(STATIC_MAX):
    key = _STATIC_DICT[i]
    if key is not None:
        _reverse_map[key] = i


# ═══ Public API ═══════════════════════════════════════════════════════════════


def resolve_dict_id(dict_id: int) -> str | None:
    """Resolve a dictionary ID to its key string.

    Checks both static and session dictionaries.

    Returns ``None`` if the ID is not assigned.
    ID 0xFF (``ID_RAW``) always returns ``None``.

    >>> resolve_dict_id(0x00)
    'tool'
    >>> resolve_dict_id(0xFF)
    """
    if dict_id < STATIC_MAX:
        return _STATIC_DICT[dict_id]
    if dict_id < SESSION_MAX:
        return _session_forward[dict_id - STATIC_MAX]
    return None


def lookup_dict_id(key: str) -> int | None:
    """O(1) reverse lookup: find the dictionary ID for *key*.

    Checks both static and session dictionaries.

    >>> lookup_dict_id("tool")
    0
    >>> lookup_dict_id("nonexistent")
    """
    # Try static dict first
    sid = _reverse_map.get(key)
    if sid is not None:
        return sid
    # Then session dict
    return _session_reverse.get(key)


# ═══ Session dictionary (0x80..0xFE, 127 dynamic slots) ═════════════════════

_session_forward: list[str | None] = [None] * (SESSION_MAX - STATIC_MAX)
_session_reverse: dict[str, int] = {}


def register_session_key(key: str, dict_id: int) -> bool:
    """Register a key in the session dictionary at a specific ID.

    Returns ``True`` if registered, ``False`` if ID is out of range.
    """
    if dict_id < STATIC_MAX or dict_id >= SESSION_MAX:
        return False
    idx = dict_id - STATIC_MAX
    old = _session_forward[idx]
    if old is not None:
        del _session_reverse[old]
    _session_forward[idx] = key
    _session_reverse[key] = dict_id
    return True


def unregister_session_key(dict_id: int) -> None:
    """Remove a key from the session dictionary."""
    if dict_id < STATIC_MAX or dict_id >= SESSION_MAX:
        return
    idx = dict_id - STATIC_MAX
    key = _session_forward[idx]
    if key is not None:
        del _session_reverse[key]
        _session_forward[idx] = None


def init_session_dict(entries: list[tuple[int, str]]) -> None:
    """Initialize the session dictionary from ``(id, key)`` pairs."""
    clear_session_dict()
    for dict_id, key in entries:
        register_session_key(key, dict_id)


def clear_session_dict() -> None:
    """Remove all session dictionary entries."""
    _session_forward[:] = [None] * len(_session_forward)
    _session_reverse.clear()


def session_dict_size() -> int:
    """Number of registered session entries."""
    return len(_session_reverse)
