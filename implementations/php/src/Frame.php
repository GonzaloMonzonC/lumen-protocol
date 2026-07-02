<?php
/**
 * Frame builder / parser — LUMEN binary wire format.
 *
 * Wire format:
 *   [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN bytes]
 *
 * Ported from Python src/lumen/frame.py.
 */

namespace Lumen;

final class Frame
{
    // Types
    public const REQUEST       = 0x01;
    public const RESPONSE      = 0x02;
    public const NOTIFY        = 0x03;
    public const STREAM_DATA   = 0x04;
    public const SCHEMA_PATCH  = 0x05;
    public const STREAM_INIT   = 0x06;
    public const DICT_SYNC     = 0x07;
    public const DISCOVER      = 0x08;
    public const MUX           = 0x09;
    public const HEARTBEAT     = 0x0A;
    public const TRANSPORT_INIT = 0x0B;
    public const TRANSPORT_ACK  = 0x0C;
    public const BATCH          = 0x0D;
    public const FLOW_CTL       = 0x0E;
    public const PROBE          = 0x0F;
    public const PROBE_ACK      = 0x10;

    // Flags
    public const FLAG_COMPRESSED  = 0x01;
    public const FLAG_ENCRYPTED   = 0x02;
    public const FLAG_PRIORITY    = 0x04;
    public const FLAG_FRAGMENTED  = 0x08;
    public const FLAG_FLOW_PAUSE  = 0x01; // bitshares COMPRESSED in FLOW_CTL context

    /** @var array<int, string> */
    public const TYPE_NAMES = [
        self::REQUEST       => 'REQUEST',
        self::RESPONSE      => 'RESPONSE',
        self::NOTIFY        => 'NOTIFY',
        self::STREAM_DATA   => 'STREAM_DATA',
        self::SCHEMA_PATCH  => 'SCHEMA_PATCH',
        self::STREAM_INIT   => 'STREAM_INIT',
        self::DICT_SYNC     => 'DICT_SYNC',
        self::DISCOVER      => 'DISCOVER',
        self::MUX           => 'MUX',
        self::HEARTBEAT     => 'HEARTBEAT',
        self::TRANSPORT_INIT => 'TRANSPORT_INIT',
        self::TRANSPORT_ACK => 'TRANSPORT_ACK',
        self::BATCH         => 'BATCH',
        self::FLOW_CTL      => 'FLOW_CTL',
        self::PROBE         => 'PROBE',
        self::PROBE_ACK     => 'PROBE_ACK',
    ];

    // ── Build ───────────────────────────────────────────────────────────

    /** Build raw wire bytes for a frame. */
    public static function buildWire(int $frameType, int $flags, string $payload): string
    {
        $lenBuf = Hyb128::encodeBytes(strlen($payload));
        return $lenBuf . chr($frameType) . chr($flags) . $payload;
    }

    /** Build a FrameData object (with optional in-buffer write at offset). */
    public static function buildFrame(
        int $frameType,
        int $flags = 0,
        string $payload = '',
        ?string &$buf = null,
        int $offset = 0
    ): FrameData {
        $wire = self::buildWire($frameType, $flags, $payload);
        if ($buf !== null) {
            $buf = substr_replace($buf ?? '', $wire, $offset, strlen($wire));
        }
        return new FrameData($frameType, $flags, $payload);
    }

    /** Total wire size for a frame with the given payload length. */
    public static function buildSize(int $payloadLen): int
    {
        return Hyb128::encodedLen($payloadLen) + 2 + $payloadLen;
    }

    // ── Parse ───────────────────────────────────────────────────────────

    /**
     * Attempt to parse one LUMEN frame from $data at $offset.
     *
     * Returns:
     *   - ParseResultComplete on success
     *   - ParseResultIncomplete if not enough data for header
     *   - ParseResultIncompletePayload if header parsed but payload incomplete
     *   - ParseResultError if malformed
     */
    public static function parseFrame(string $data, int $offset = 0): ParseResult
    {
        $available = strlen($data) - $offset;
        if ($available <= 0) return ParseResultIncomplete::instance();

        // Decode Hyb128 payload length
        $decoded = Hyb128::decode($data, $offset);
        if ($decoded === null) return ParseResultIncomplete::instance();

        $payloadLen = $decoded['value'];
        $headerLen = $decoded['headerLen'];

        // Need TYPE(1) + FLAGS(1) + payload
        $needed = $headerLen + 2 + $payloadLen;
        if ($available < $needed) {
            return new ParseResultIncompletePayload($needed, $available);
        }

        $typePos = $offset + $headerLen;
        $frameType = ord($data[$typePos]);
        $flags = ord($data[$typePos + 1]);

        $payloadStart = $typePos + 2;
        $payload = substr($data, $payloadStart, $payloadLen);

        $frame = new FrameData($frameType, $flags, $payload);
        return new ParseResultComplete($frame, $needed);
    }
}
