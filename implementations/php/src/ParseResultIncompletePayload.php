<?php
/** ParseResultIncompletePayload — header parsed but payload incomplete. */

namespace Lumen;

final class ParseResultIncompletePayload implements ParseResult
{
    public function __construct(
        public readonly int $expected,
        public readonly int $available,
    ) {}
}
