<?php
/**
 * ParseResult — sum type for Frame::parseFrame() return value.
 *
 * Hierarchy matches Python's ParseComplete | ParseIncomplete | ParseIncompletePayload.
 */

namespace Lumen;

/** Base interface for all parse result types. */
interface ParseResult {}

// ── ParseResultComplete ─────────────────────────────────────────────────────

final class ParseResultComplete implements ParseResult
{
    public function __construct(
        public readonly FrameData $frame,
        public readonly int $consumed,
    ) {}
}

// ── ParseResultIncomplete (not enough data for header) ──────────────────────

final class ParseResultIncomplete implements ParseResult
{
    private static ?self $instance = null;

    public static function instance(): self
    {
        return self::$instance ??= new self();
    }

    private function __construct() {}
}

// ── ParseResultIncompletePayload (header parsed, payload incomplete) ────────

final class ParseResultIncompletePayload implements ParseResult
{
    public function __construct(
        public readonly int $expected,
        public readonly int $available,
    ) {}
}
