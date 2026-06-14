/// <summary>
/// LUMEN static dictionary — 128 predefined key mappings (0x00–0x7F).
/// Mirrors implementations/rust/src/dict.rs exactly.
/// </summary>
namespace Lumen;

public static class Dict
{
    /// <summary>Raw UTF-8 key sentinel.</summary>
    public const byte ID_RAW = 0xFF;

    /// <summary>Maximum static dictionary ID + 1.</summary>
    public const int STATIC_MAX = 128;

    /// <summary>Maximum session dictionary IDs.</summary>
    public const int SESSION_MAX = 127;

    /// <summary>Total entries (static + session).</summary>
    public const int TOTAL_ENTRIES = 255;

    private static readonly string[] _byId = new string[STATIC_MAX];
    private static readonly Dictionary<string, byte> _byKey = new(STATIC_MAX);

    // Session dictionary (0x80..0xFE, 127 dynamic slots)
    private static readonly string?[] _sessionForward = new string?[SESSION_MAX];
    private static readonly Dictionary<string, byte> _sessionReverse = new(SESSION_MAX);

    static Dict()
    {
        var entries = new (byte id, string key)[]
        {
            (0x00, "tool"), (0x01, "arguments"), (0x02, "result"), (0x03, "error"),
            (0x04, "id"), (0x05, "name"), (0x06, "description"), (0x07, "content"),
            (0x08, "text"), (0x09, "type"), (0x0A, "method"), (0x0B, "params"),
            (0x0C, "jsonrpc"), (0x0D, "data"), (0x0E, "code"), (0x0F, "message"),
            (0x10, "input"), (0x11, "output"), (0x12, "stream"), (0x13, "uri"),
            (0x14, "mimeType"), (0x15, "encoding"), (0x16, "language"), (0x17, "title"),
            (0x18, "value"), (0x19, "key"), (0x1A, "path"), (0x1B, "version"),
            (0x1C, "schema"), (0x1D, "default"), (0x1E, "required"), (0x1F, "properties"),
            (0x20, "resources"), (0x21, "tools"), (0x22, "prompts"), (0x23, "resource"),
            (0x24, "prompt"), (0x25, "handler"), (0x26, "capabilities"), (0x27, "permissions"),
            (0x28, "scope"), (0x29, "tags"), (0x2A, "category"), (0x2B, "icon"),
            (0x2C, "metadata"), (0x2D, "timestamp"), (0x2E, "status"), (0x2F, "progress"),
            (0x30, "severity"), (0x31, "details"), (0x32, "cause"), (0x33, "stack"),
            (0x34, "line"), (0x35, "column"), (0x36, "source"), (0x37, "retry"),
            (0x38, "timeout"), (0x39, "limit"), (0x3A, "offset"), (0x3B, "count"),
            (0x3C, "total"), (0x3D, "page"), (0x3E, "cursor"), (0x3F, "next"),
            (0x40, "model"), (0x41, "provider"), (0x42, "temperature"), (0x43, "max_tokens"),
            (0x44, "stop"), (0x45, "frequency_penalty"), (0x46, "presence_penalty"), (0x47, "top_p"),
            (0x48, "logprobs"), (0x49, "user"), (0x4A, "system"), (0x4B, "assistant"),
            (0x4C, "function"), (0x4D, "tool_calls"), (0x4E, "finish_reason"), (0x4F, "usage"),
            (0x50, "url"), (0x51, "http_method"), (0x52, "headers"), (0x53, "body"),
            (0x54, "query"), (0x55, "http_status"), (0x56, "cookie"), (0x57, "session"),
            (0x58, "token"), (0x59, "auth"), (0x5A, "redirect"), (0x5B, "host"),
            (0x5C, "port"), (0x5D, "origin"), (0x5E, "referrer"), (0x5F, "agent"),
            (0x60, "filename"), (0x61, "directory"), (0x62, "extension"), (0x63, "size"),
            (0x64, "modified"), (0x65, "created"), (0x66, "accessed"), (0x67, "mode"),
            (0x68, "owner"), (0x69, "group"), (0x6A, "symlink"), (0x6B, "binary"),
            (0x6C, "base64"), (0x6D, "hash"), (0x6E, "algorithm"), (0x6F, "chunk"),
            (0x70, "execute"), (0x71, "read"), (0x72, "write"), (0x73, "delete"),
            (0x74, "update"), (0x75, "create"), (0x76, "search"), (0x77, "list"),
            (0x78, "get"), (0x79, "set"), (0x7A, "watch"), (0x7B, "subscribe"),
            (0x7C, "notify"), (0x7D, "cancel"), (0x7E, "pause"), (0x7F, "resume"),
        };

        foreach (var (id, key) in entries)
        {
            _byId[id] = key;
            _byKey[key] = id;
        }
    }

    /// <summary>Look up a key → dictionary ID. Checks static then session dict. Returns null if not found.</summary>
    public static byte? LookupId(string key)
    {
        if (_byKey.TryGetValue(key, out var id))
            return id;
        return _sessionReverse.TryGetValue(key, out var sid) ? sid : null;
    }

    /// <summary>Resolve a dictionary ID → key string. Checks static then session. Returns null if out of range.</summary>
    public static string? ResolveId(byte id)
    {
        if (id < STATIC_MAX)
            return _byId[id];
        if (id < 0xFF)
            return _sessionForward[id - STATIC_MAX];
        return null;
    }

    // ═══ Session dictionary (0x80..0xFE, 127 dynamic slots) ═════════════════

    /// <summary>Register a key in the session dictionary at a specific ID. Returns true on success.</summary>
    public static bool RegisterSessionKey(string key, byte id)
    {
        if (id < STATIC_MAX || id >= 0xFF)
            return false;
        int idx = id - STATIC_MAX;
        var old = _sessionForward[idx];
        if (old is not null)
            _sessionReverse.Remove(old);
        _sessionForward[idx] = key;
        _sessionReverse[key] = id;
        return true;
    }

    /// <summary>Remove a key from the session dictionary by ID.</summary>
    public static void UnregisterSessionKey(byte id)
    {
        if (id < STATIC_MAX || id >= 0xFF)
            return;
        int idx = id - STATIC_MAX;
        var key = _sessionForward[idx];
        if (key is not null)
        {
            _sessionReverse.Remove(key);
            _sessionForward[idx] = null;
        }
    }

    /// <summary>Initialize the session dictionary from (id, key) pairs.</summary>
    public static void InitSessionDict(IEnumerable<(byte id, string key)> entries)
    {
        ClearSessionDict();
        foreach (var (id, key) in entries)
            RegisterSessionKey(key, id);
    }

    /// <summary>Remove all session dictionary entries.</summary>
    public static void ClearSessionDict()
    {
        Array.Clear(_sessionForward, 0, _sessionForward.Length);
        _sessionReverse.Clear();
    }

    /// <summary>Number of registered session entries.</summary>
    public static int SessionDictSize => _sessionReverse.Count;
}
