/**
 * LUMEN C FFI — stable ABI for 20+ languages.
 *
 * ## Quick start
 *
 * ```c
 * #include "lumen.h"
 * #include <stdio.h>
 *
 * int main() {
 *     const char *json = "{\"method\":\"ping\"}";
 *     uint8_t *out = NULL;
 *     size_t out_len = 0;
 *
 *     if (lumen_compress((const uint8_t*)json, strlen(json), &out, &out_len) == 0) {
 *         printf("Compressed: %zu bytes\n", out_len);
 *         // ... send over the wire ...
 *         lumen_free(out, out_len);
 *     }
 *     return 0;
 * }
 * ```
 *
 * ## Building
 *
 * ```bash
 * cargo build --release
 * # On Windows: target/release/lumen.dll
 * # On Linux:   target/release/liblumen.so
 * # On macOS:   target/release/liblumen.dylib
 * ```
 *
 * ## Linking
 *
 * ```bash
 * # Dynamic
 * gcc -o myapp myapp.c -Ltarget/release -llumen
 *
 * # Or copy the shared library and header to your project.
 * ```
 */

#ifndef LUMEN_H
#define LUMEN_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#ifdef _WIN32
  #ifdef LUMEN_STATIC
    #define LUMEN_API
  #else
    #ifdef LUMEN_BUILD_DLL
      #define LUMEN_API __declspec(dllexport)
    #else
      #define LUMEN_API __declspec(dllimport)
    #endif
  #endif
#else
  #define LUMEN_API __attribute__((visibility("default")))
#endif

/// Version number: (major << 24) | (minor << 16) | (patch << 8).
/// e.g. 0x00010000 = v0.1.0
LUMEN_API uint32_t lumen_version(void);

/// Get the last error message (thread-safe).
///
/// Returns a null-terminated UTF-8 string. The pointer is valid until
/// the next call to any lumen_* function on the same thread.
/// Returns NULL if there is no error.
LUMEN_API const char *lumen_error_message(void);

/// Compress a JSON string into LUMEN compact binary.
///
/// @param json_ptr   Pointer to UTF-8 JSON input (need not be null-terminated).
/// @param json_len   Length of JSON input in bytes.
/// @param[out] out_ptr  Receives pointer to heap-allocated compressed buffer.
/// @param[out] out_len  Receives length of compressed buffer in bytes.
///
/// @return 0 on success, -1 on error (call lumen_error_message() for details).
///
/// On success the caller MUST free `*out_ptr` with lumen_free().
LUMEN_API int32_t lumen_compress(
    const uint8_t *json_ptr,
    size_t          json_len,
    uint8_t       **out_ptr,
    size_t         *out_len
);

/// Decompress LUMEN binary into a JSON string.
///
/// @param data_ptr   Pointer to LUMEN compact binary input.
/// @param data_len   Length of binary input in bytes.
/// @param[out] out_ptr  Receives pointer to heap-allocated JSON UTF-8 string.
/// @param[out] out_len  Receives length of JSON string in bytes.
///
/// @return 0 on success, -1 on error.
///
/// On success the caller MUST free `*out_ptr` with lumen_free().
LUMEN_API int32_t lumen_decompress(
    const uint8_t *data_ptr,
    size_t          data_len,
    uint8_t       **out_ptr,
    size_t         *out_len
);

/// Free a buffer previously returned by lumen_compress() or lumen_decompress().
///
/// Safe to call with NULL (no-op). `len` must match the length returned
/// by the corresponding function.
LUMEN_API void lumen_free(uint8_t *ptr, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* LUMEN_H */
