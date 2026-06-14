<?php
/**
 * Manual PSR-4 autoloader — fallback when Composer is not available.
 * Requires PHP 8.1+.
 */

spl_autoload_register(function (string $class): void {
    $prefix = 'Lumen\\';
    if (!str_starts_with($class, $prefix)) return;

    $relativeClass = substr($class, strlen($prefix));
    $file = __DIR__ . '/src/' . str_replace('\\', '/', $relativeClass) . '.php';

    if (file_exists($file)) {
        require $file;
    }
});
