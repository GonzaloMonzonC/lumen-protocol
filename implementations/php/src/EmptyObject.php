<?php
/** Sentinel value representing the JSON empty object `{}` as distinct from `[]`.
 *  PHP's json_decode('{}', true) and json_decode('[]', true) both return [],
 *  so this class preserves the distinction when decoding with assoc=false. */

namespace Lumen;

final class EmptyObject {}
