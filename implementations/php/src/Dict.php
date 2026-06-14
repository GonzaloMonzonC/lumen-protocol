<?php
/**
 * Dictionary — 128 static + 127 session IDs for key compression.
 *
 * Range         Purpose
 * 0x00-0x7F     Static dictionary (128)
 * 0x80-0xFE     Session dictionary (127)
 * 0xFF          Raw UTF-8 key (escape)
 */

namespace Lumen;

final class Dict
{
    public const STATIC_MAX = 0x80;
    public const SESSION_MAX = 0xFF;
    public const ID_RAW = 0xFF;

    /** @var array<int, string|null> ID → key */
    private static array $resolveTable = [];

    /** @var array<string, int> key → ID */
    private static array $lookupTable = [];

    private static bool $initialized = false;

    private static function init(): void
    {
        if (self::$initialized) return;
        self::$initialized = true;

        $entries = [
            0x00 => 'tool',        0x01 => 'arguments',    0x02 => 'result',
            0x03 => 'error',       0x04 => 'id',           0x05 => 'name',
            0x06 => 'description', 0x07 => 'content',      0x08 => 'text',
            0x09 => 'type',        0x0A => 'method',       0x0B => 'params',
            0x0C => 'jsonrpc',     0x0D => 'data',         0x0E => 'code',
            0x0F => 'message',

            0x10 => 'input',       0x11 => 'output',       0x12 => 'stream',
            0x13 => 'uri',         0x14 => 'mimeType',     0x15 => 'encoding',
            0x16 => 'language',    0x17 => 'title',        0x18 => 'value',
            0x19 => 'key',         0x1A => 'path',         0x1B => 'version',
            0x1C => 'schema',      0x1D => 'default',      0x1E => 'required',
            0x1F => 'properties',

            0x20 => 'resources',   0x21 => 'tools',        0x22 => 'prompts',
            0x23 => 'resource',    0x24 => 'prompt',       0x25 => 'handler',
            0x26 => 'capabilities',0x27 => 'permissions',  0x28 => 'scope',
            0x29 => 'tags',        0x2A => 'category',     0x2B => 'icon',
            0x2C => 'metadata',    0x2D => 'timestamp',    0x2E => 'status',
            0x2F => 'progress',

            0x30 => 'severity',    0x31 => 'details',      0x32 => 'cause',
            0x33 => 'stack',       0x34 => 'line',         0x35 => 'column',
            0x36 => 'source',      0x37 => 'retry',        0x38 => 'timeout',
            0x39 => 'limit',       0x3A => 'offset',       0x3B => 'count',
            0x3C => 'total',       0x3D => 'page',         0x3E => 'cursor',
            0x3F => 'next',

            0x40 => 'model',       0x41 => 'provider',      0x42 => 'temperature',
            0x43 => 'max_tokens',  0x44 => 'stop',          0x45 => 'top_p',
            0x46 => 'frequency_penalty', 0x47 => 'presence_penalty',
            0x48 => 'logprobs',    0x49 => 'echo',          0x4A => 'n',
            0x4B => 'seed',        0x4C => 'user',          0x4D => 'system',
            0x4E => 'assistant',   0x4F => 'usage',

            0x50 => 'prompt_tokens',   0x51 => 'completion_tokens',
            0x52 => 'total_tokens',    0x53 => 'finish_reason',
            0x54 => 'index',           0x55 => 'delta',
            0x56 => 'choices',         0x57 => 'role',
            0x58 => 'function',        0x59 => 'functions',
            0x5A => 'parameters',      0x5B => 'enum',
            0x5C => 'items',           0x5D => 'additionalProperties',
            0x5E => 'oneOf',           0x5F => 'anyOf',

            0x60 => 'allOf',           0x61 => 'not',
            0x62 => 'minLength',       0x63 => 'maxLength',
            0x64 => 'minimum',         0x65 => 'maximum',
            0x66 => 'exclusiveMinimum',0x67 => 'exclusiveMaximum',
            0x68 => 'pattern',         0x69 => 'format',
            0x6A => 'readOnly',        0x6B => 'writeOnly',
            0x6C => 'deprecated',      0x6D => 'examples',
            0x6E => 'const',           0x6F => 'if',

            0x70 => 'then',            0x71 => 'else',
            0x72 => 'inputSchema',     0x73 => 'outputSchema',
            0x74 => 'transport',       0x75 => 'protocolVersion',
            0x76 => 'serverInfo',      0x77 => 'clientInfo',
            0x78 => 'hints',           0x79 => 'sessionId',
            0x7A => 'traceId',         0x7B => 'parentId',
            0x7C => 'root',            0x7D => 'create',
            0x7E => 'update',          0x7F => 'delete',
        ];

        foreach ($entries as $id => $key) {
            self::$resolveTable[$id] = $key;
            self::$lookupTable[$key] = $id;
        }
    }

    /** ID → key (O(1) array lookup). Returns null for unknown IDs. */
    public static function resolve(int $id): ?string
    {
        self::init();
        return self::$resolveTable[$id] ?? null;
    }

    /** key → ID (O(1) hash lookup). Returns null if not in dictionary. */
    public static function lookup(string $key): ?int
    {
        self::init();
        return self::$lookupTable[$key] ?? null;
    }
}
