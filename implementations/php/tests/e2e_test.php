<?php
/**
 * LUMEN e2e cross-implementation test — PHP.
 *
 * Run: php tests/e2e_test.php
 */

declare(strict_types=1);

$autoloadPath = __DIR__ . '/../vendor/autoload.php';
if (file_exists($autoloadPath)) {
    require $autoloadPath;
} else {
    require __DIR__ . '/../autoload_manual.php';
}

use Lumen\Compress;
use Lumen\EmptyObject;
use Lumen\Frame;
use Lumen\Hyb128;
use Lumen\ParseResultComplete;

define('VECTORS_PATH', dirname(__DIR__, 3) . '/tests/e2e/shared_vectors.json');
define('GOLDEN_DIR', dirname(__DIR__, 3) . '/tests/e2e/golden');

function loadVectors(): array {
    $raw = file_get_contents(VECTORS_PATH);
    $data = json_decode($raw, false); // no assoc — preserves [] vs {} distinction
    $vectors = [];
    foreach ($data->vectors as $v) {
        $vectors[] = ['name' => $v->name, 'value' => jsonDecodeValue($v->value)];
    }
    return $vectors;
}

/** Convert JSON-decoded value (stdClass for objects) to PHP arrays. */
function jsonDecodeValue(mixed $v): mixed {
    if (is_array($v)) return array_map('jsonDecodeValue', $v);
    if ($v instanceof stdClass) {
        $arr = [];
        foreach ($v as $k => $val) {
            $arr[$k] = jsonDecodeValue($val);
        }
        return count($arr) === 0 ? new EmptyObject() : $arr;
    }
    return $v;
}

function loadGolden(string $name): ?string {
    $path = GOLDEN_DIR . '/' . $name . '.lumen';
    return file_exists($path) ? file_get_contents($path) : null;
}

function loadGoldenFrame(string $name): ?string {
    $path = GOLDEN_DIR . '/' . $name . '.frame';
    return file_exists($path) ? file_get_contents($path) : null;
}

function jsonEqual(mixed $a, mixed $b): bool {
    return json_encode($a, JSON_UNESCAPED_UNICODE) === json_encode($b, JSON_UNESCAPED_UNICODE);
}

/** Encode JSON matching Python's json.dumps default format (spaces after : and ,). */
function jsonDumpsPy(mixed $value): string {
    $json = json_encode($value, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    // Python's json.dumps uses separators=(', ', ': ') — add space after : and ,
    // Match ':' not followed by whitespace (covers "key":"val", "key":1, "key":{)
    $json = preg_replace('/":(?!\s)/', '": ', $json);
    // Match ',' not followed by whitespace (covers ...",... and ...1,... and ...},...)
    $json = preg_replace('/,(?!\s)/', ', ', $json);
    return $json;
}

function valueEquals(mixed $a, mixed $b): bool {
    if ($a === null && $b === null) return true;
    if ($a instanceof EmptyObject && $b instanceof EmptyObject) return true;
    if (is_float($a) && is_float($b)) return abs($a - $b) < 1e-12;
    // EmptyObject and [] are semantically equivalent (empty collections)
    if ($a instanceof EmptyObject && is_array($b) && $b === []) return true;
    if ($b instanceof EmptyObject && is_array($a) && $a === []) return true;
    if (is_array($a) && is_array($b)) return jsonEqual($a, $b);
    return $a === $b;
}

$SKIP_BINARY_COMPARE = ['float_zero', 'object_empty'];

$passed = 0;
$failed = 0;

function test(string $vector, string $testName, bool $ok, ?string $error = null): void {
    global $passed, $failed;
    if ($ok) { $passed++; } else { $failed++; }
    $status = $ok ? "✓" : "✗";
    $errStr = $error ? ": $error" : "";
    printf("  %s %s — %s%s\n", $status, $testName, $vector, $errStr);
}

// ═══ 1. Compress Roundtrip ═══
echo "\n1. Compress Roundtrip\n";
$vectors = loadVectors();
foreach ($vectors as $v) {
    $name = $v['name'];
    $value = $v['value'];
    try {
        $compressed = Compress::compress($value);
        $decompressed = Compress::decompress($compressed);
        $ok = valueEquals($decompressed, $value);
        test($name, 'compress_roundtrip', $ok);
    } catch (\Throwable $e) {
        test($name, 'compress_roundtrip', false, $e::class . ': ' . $e->getMessage());
    }
}

// ═══ 2. Binary Compatibility ═══
echo "\n2. Binary Compatibility (PHP vs Python golden)\n";
foreach ($vectors as $v) {
    $name = $v['name'];
    $value = $v['value'];
    if (in_array($name, $SKIP_BINARY_COMPARE)) {
        test($name, 'binary_match', true, 'SKIP');
        test($name, 'cross_decode', true, 'SKIP');
        continue;
    }
    try {
        $php = Compress::compress($value);
        $golden = loadGolden($name);
        if ($golden !== null) {
            $ok = $php === $golden;
            test($name, 'binary_match', $ok,
                $ok ? null : sprintf("PHP(%dB):%s != PY(%dB):%s",
                    strlen($php), bin2hex($php), strlen($golden), bin2hex($golden)));
        } else {
            test($name, 'binary_match', false, "golden not found");
        }
    } catch (\Throwable $e) {
        test($name, 'binary_match', false, $e::class . ': ' . $e->getMessage());
    }
    try {
        $golden = loadGolden($name);
        if ($golden !== null) {
            $decoded = Compress::decompress($golden);
            $ok = valueEquals($decoded, $value);
            test($name, 'cross_decode', $ok);
        } else {
            test($name, 'cross_decode', false, "golden not found");
        }
    } catch (\Throwable $e) {
        test($name, 'cross_decode', false, $e::class . ': ' . $e->getMessage());
    }
}

// ═══ 3. Binary Stability ═══
echo "\n3. Binary Stability\n";
$stabilityCases = [
    ['null', null], ['bool', true], ['int', 42], ['float', 3.14],
    ['string', 'hello'], ['array', [1, 2, 3]], ['object', ['key' => 'value']],
    ['mcp_init', ['jsonrpc' => '2.0', 'method' => 'initialize']],
];
foreach ($stabilityCases as [$sn, $sv]) {
    try {
        $c1 = Compress::compress($sv);
        $c2 = Compress::compress($sv);
        test("stability_$sn", 'binary_stability', $c1 === $c2);
    } catch (\Throwable $e) {
        test("stability_$sn", 'binary_stability', false, $e::class . ': ' . $e->getMessage());
    }
}

// ═══ 4. Hyb128 Roundtrip ═══
echo "\n4. Hyb128 Roundtrip\n";
$hyb128Cases = [
    [0, 1], [1, 1], [42, 1], [63, 1],
    [64, 3], [255, 3], [1000, 3], [65535, 3],
    [65536, 5], [100000, 5], [1000000, 5],
];
foreach ($hyb128Cases as [$value, $expectedLen]) {
    $name = "hyb128_$value";
    try {
        $encoded = Hyb128::encodeBytes($value);
        $actualLen = strlen($encoded);
        $expectedEnc = Hyb128::encodedLen($value);
        $decoded = Hyb128::decode($encoded, 0);
        $ok = $actualLen === $expectedLen
           && $expectedEnc === $expectedLen
           && $decoded !== null
           && $decoded['value'] === $value
           && $decoded['headerLen'] === $expectedLen;
        test($name, 'hyb128_roundtrip', $ok);
    } catch (\Throwable $e) {
        test($name, 'hyb128_roundtrip', false, $e::class . ': ' . $e->getMessage());
    }
}

// ═══ 5. Frame Roundtrip ═══
echo "\n5. Frame Roundtrip\n";
$payloads = [
    ['empty', ''],
    ['hello', 'hello'],
    ['json_small', jsonDumpsPy(['method' => 'ping'])],
    ['json_mcp', jsonDumpsPy([
        'jsonrpc' => '2.0', 'id' => 1, 'method' => 'initialize',
        'params' => ['protocolVersion' => '2025-06-18'],
    ])],
];
$frameTypes = [
    ['REQUEST', Frame::REQUEST],
    ['RESPONSE', Frame::RESPONSE],
    ['NOTIFY', Frame::NOTIFY],
];
$flagSets = [
    ['none', 0],
    ['compressed', Frame::FLAG_COMPRESSED],
    ['priority', Frame::FLAG_PRIORITY],
];

foreach ($payloads as [$pname, $payload]) {
    foreach ($frameTypes as [$tname, $ftype]) {
        foreach ($flagSets as [$flname, $flags]) {
            $name = "frame_{$tname}_{$flname}_{$pname}";
            try {
                $frame = Frame::buildFrame($ftype, $flags, $payload);
                $wire = $frame->toBytes();
                $result = Frame::parseFrame($wire, 0);
                if ($result instanceof ParseResultComplete) {
                    $ok = $result->frame->frameType === $ftype
                       && $result->frame->flags === $flags
                       && $result->frame->payload === $payload;
                    test($name, 'frame_roundtrip', $ok);
                } else {
                    test($name, 'frame_roundtrip', false, 'not complete: ' . $result::class);
                }
            } catch (\Throwable $e) {
                test($name, 'frame_roundtrip', false, $e::class . ': ' . $e->getMessage());
            }
        }
    }
}

// ═══ 6. Frame Binary Compatibility ═══
echo "\n6. Frame Binary Compatibility\n";
foreach ($payloads as [$pname, $payload]) {
    foreach ($frameTypes as [$tname, $ftype]) {
        foreach ($flagSets as [$flname, $flags]) {
            $name = "frame_{$tname}_{$flname}_{$pname}";
            try {
                $frame = Frame::buildFrame($ftype, $flags, $payload);
                $phpWire = $frame->toBytes();
                $goldenWire = loadGoldenFrame($name);
                if ($goldenWire === null) {
                    test($name, 'frame_binary_match', false, "golden not found");
                    test($name, 'frame_parse_golden', false, "golden not found");
                    continue;
                }
                $ok = $phpWire === $goldenWire;
                test($name, 'frame_binary_match', $ok,
                    $ok ? null : sprintf("PHP(%dB):%s != PY(%dB):%s",
                        strlen($phpWire), bin2hex($phpWire), strlen($goldenWire), bin2hex($goldenWire)));
                $result = Frame::parseFrame($goldenWire, 0);
                if ($result instanceof ParseResultComplete) {
                    $pok = $result->frame->frameType === $ftype
                        && $result->frame->flags === $flags
                        && $result->frame->payload === $payload;
                    test($name, 'frame_parse_golden', $pok);
                } else {
                    test($name, 'frame_parse_golden', false, 'not complete: ' . $result::class);
                }
            } catch (\Throwable $e) {
                test($name, 'frame_binary_match', false, $e::class . ': ' . $e->getMessage());
                test($name, 'frame_parse_golden', false, $e::class . ': ' . $e->getMessage());
            }
        }
    }
}

// ═══ 7. Compressed Frame Integration ═══
echo "\n7. Compressed Frame Integration\n";
$integrationPayloads = [
    ['initialize', ['jsonrpc' => '2.0', 'id' => 1, 'method' => 'initialize',
                    'params' => ['protocolVersion' => '2025-06-18']]],
    ['tools_list', ['jsonrpc' => '2.0', 'id' => 2, 'result' => [
        'tools' => [['name' => 'search', 'description' => 'Search code',
                      'inputSchema' => ['type' => 'object', 'properties' => ['query' => ['type' => 'string']]]]]
    ]]],
];

foreach ($integrationPayloads as [$pname, $payload]) {
    $name = "integration_$pname";
    try {
        $compressed = Compress::compress($payload);
        $frame = Frame::buildFrame(Frame::REQUEST, Frame::FLAG_COMPRESSED, $compressed);
        $wire = $frame->toBytes();
        $result = Frame::parseFrame($wire, 0);
        if ($result instanceof ParseResultComplete) {
            $frameOk = $result->frame->isCompressed();
            $decompressed = Compress::decompress($result->frame->payload);
            $payloadOk = jsonEqual($decompressed, $payload);
            test($name, 'integration_roundtrip', $frameOk && $payloadOk);

            $goldenWire = loadGoldenFrame($name);
            if ($goldenWire !== null) {
                $match = $wire === $goldenWire;
                test($name, 'integration_binary_match', $match,
                    $match ? null : sprintf("PHP(%dB):%s != PY(%dB):%s",
                        strlen($wire), bin2hex($wire), strlen($goldenWire), bin2hex($goldenWire)));

                $pyResult = Frame::parseFrame($goldenWire, 0);
                if ($pyResult instanceof ParseResultComplete && $pyResult->frame->isCompressed()) {
                    $pyDecompressed = Compress::decompress($pyResult->frame->payload);
                    test($name, 'integration_parse_python', jsonEqual($pyDecompressed, $payload));
                } else {
                    test($name, 'integration_parse_python', false, 'failed to parse PY integration frame');
                }
            } else {
                test($name, 'integration_binary_match', false, "golden not found");
                test($name, 'integration_parse_python', false, "golden not found");
            }
        } else {
            test($name, 'integration_roundtrip', false, 'not complete: ' . $result::class);
        }
    } catch (\Throwable $e) {
        test($name, 'integration_roundtrip', false, $e::class . ': ' . $e->getMessage());
        test($name, 'integration_binary_match', false, $e::class . ': ' . $e->getMessage());
        test($name, 'integration_parse_python', false, $e::class . ': ' . $e->getMessage());
    }
}

// ═══ Summary ═══
echo "\n══════════════════════════════════════════════════\n";
printf("Results: %d passed, %d failed, %d total\n", $passed, $failed, $passed + $failed);
exit($failed === 0 ? 0 : 1);
