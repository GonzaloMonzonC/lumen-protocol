#!/usr/bin/env bash
# Construye liblumen_mlight.so para i686 glibc (i686-unknown-linux-gnu).
# musl NO soporta cdylib en Rust; glibc si.
set -u
cd /c/Users/gonzalo/Documents/GitHub/lumen-protocol || exit 1

W="C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686"
export ZIG_GLOBAL_CACHE_DIR="C:/Users/gonzalo/.zig-cache-global"
export ZIG_LOCAL_CACHE_DIR="C:/tmp/ziglocal"
export CC_i686_unknown_linux_gnu="$W/zigcc-i686-gnu.exe"
export CXX_i686_unknown_linux_gnu="$W/zigcc-i686-gnu.exe"
export AR_i686_unknown_linux_gnu="$W/zigar-i686-gnu.exe"
export CARGO_TARGET_I686_UNKNOWN_LINUX_GNU_LINKER="$W/zigcc-i686-gnu.exe"

echo "=== BUILD mlight-so (cdylib) i686-unknown-linux-gnu ==="
cargo build --release --target i686-unknown-linux-gnu \
  --manifest-path build-iso-i686/mlight-so/Cargo.toml 2>&1 | tail -15

echo "=== ARTEFACTO ==="
ls -lh build-iso-i686/mlight-so/target/i686-unknown-linux-gnu/release/*.so 2>/dev/null || echo "(sin .so)"
