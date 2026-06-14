<?php
/**
 * FrameData — parsed LUMEN frame header + payload.
 *
 * Ported from Python src/lumen/frame.py (class Frame).
 */

namespace Lumen;

final class FrameData
{
    /**
     * @param int    $frameType  One of Frame::REQUEST, Frame::RESPONSE, etc.
     * @param int    $flags      Bitmask of Frame::FLAG_* constants.
     * @param string $payload    Raw payload bytes (may be compressed).
     */
    public function __construct(
        public readonly int $frameType,
        public readonly int $flags,
        public readonly string $payload,
    ) {}

    /** Serialize this frame to wire format bytes. */
    public function toBytes(): string
    {
        return Frame::buildWire($this->frameType, $this->flags, $this->payload);
    }

    public function isCompressed(): bool
    {
        return ($this->flags & Frame::FLAG_COMPRESSED) !== 0;
    }

    public function isEncrypted(): bool
    {
        return ($this->flags & Frame::FLAG_ENCRYPTED) !== 0;
    }

    public function isPriority(): bool
    {
        return ($this->flags & Frame::FLAG_PRIORITY) !== 0;
    }

    public function isFragmented(): bool
    {
        return ($this->flags & Frame::FLAG_FRAGMENTED) !== 0;
    }

    public function typeName(): string
    {
        return Frame::TYPE_NAMES[$this->frameType] ?? 'UNKNOWN(0x' . dechex($this->frameType) . ')';
    }
}
