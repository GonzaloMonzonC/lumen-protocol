<?php
/** ParseResultIncomplete — not enough data for frame header. */

namespace Lumen;

final class ParseResultIncomplete implements ParseResult
{
    private static ?self $instance = null;

    public static function instance(): self
    {
        return self::$instance ??= new self();
    }

    private function __construct() {}
}
