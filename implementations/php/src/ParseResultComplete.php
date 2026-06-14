<?php
/** ParseResultComplete — frame parsed successfully. */

namespace Lumen;

final class ParseResultComplete implements ParseResult
{
    public function __construct(
        public readonly FrameData $frame,
        public readonly int $consumed,
    ) {}
}
