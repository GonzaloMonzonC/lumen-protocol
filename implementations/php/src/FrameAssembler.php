<?php
declare(strict_types=1);

namespace Lumen;

/**
 * FrameAssembler — streaming frame reassembler.
 *
 * Accumulates raw bytes and yields complete LUMEN frames as they become
 * available. Incomplete data is retained for the next call.
 */
class FrameAssembler
{
    private string $buf = '';

    /**
     * Feed a raw byte chunk into the assembler.
     *
     * @return array<ParseResultComplete> List of complete frames parsed.
     */
    public function push(string $chunk): array
    {
        $this->buf .= $chunk;
        $frames = [];

        while (true) {
            $result = Frame::parseFrame($this->buf, 0);

            if ($result instanceof ParseResultComplete) {
                $frames[] = $result;
                $consumed = $result->consumed;
                $this->buf = substr($this->buf, $consumed);
                continue;
            }

            break;
        }

        return $frames;
    }

    /** Return trailing bytes and clear the buffer. */
    public function flush(): string
    {
        $data = $this->buf;
        $this->buf = '';
        return $data;
    }

    /** Clear internal buffer. */
    public function reset(): void
    {
        $this->buf = '';
    }

    /** Number of buffered bytes. */
    public function len(): int
    {
        return strlen($this->buf);
    }
}
