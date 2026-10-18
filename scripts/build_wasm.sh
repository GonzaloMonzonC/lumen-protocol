#!/usr/bin/env bash
# build_wasm.sh — construye el paquete wasm de lumen-m-light (pkg/).
#
# POR QUE EXISTE
# --------------
# El build de wasm NO es el build por defecto. Con los features de por defecto
# (sqlite, minreq, dll) falla en wasm32 por una cadena concreta:
#
#     minreq -> rustls -> ring -> getrandom
#
# y getrandom no compila en wasm32-unknown-unknown sin el backend JS. El error
# que se ve es este, y despues arrastra a ring y libsqlite3-sys:
#
#     error: the wasm*-unknown-unknown targets are not supported by default,
#     you may need to enable the "js" feature
#     error: failed to run custom build command for `ring v0.17.14`
#
# NO hace falta añadir `getrandom = { features = ["js"] }` al Cargo.toml:
# `--no-default-features --features wasm` ya lo deja fuera del grafo. El
# problema es olvidar esos flags, no una dependencia que falte.
#
# Uso:
#   bash scripts/build_wasm.sh            # release (lo normal)
#   bash scripts/build_wasm.sh --debug    # debug, para depurar
set -euo pipefail

CRATE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/implementations/rust/lumen-m-light"
PERFIL="--release"
case "${1:-}" in
  --debug) PERFIL="" ;;
  --release|"") PERFIL="--release" ;;
  *) echo "uso: $0 [--debug|--release]" >&2; exit 2 ;;
esac

echo "== crate: $CRATE"
cd "$CRATE"

# 1. target wasm
if ! rustup target list --installed 2>/dev/null | grep -q '^wasm32-unknown-unknown$'; then
  echo "== instalando target wasm32-unknown-unknown"
  rustup target add wasm32-unknown-unknown
fi

# 2. wasm-bindgen-cli con la MISMA version que el wasm-bindgen del lock.
#    Si no casan, el glue JS y el .wasm no se hablan (falla al instanciar).
VER_LOCK=$(grep -A1 '^name = "wasm-bindgen"$' Cargo.lock | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)
VER_CLI=$(wasm-bindgen --version 2>/dev/null | awk '{print $2}' || true)
if [ "${VER_CLI:-}" != "${VER_LOCK:-}" ]; then
  echo "== wasm-bindgen-cli $VER_CLI != lock $VER_LOCK -> instalando"
  cargo install wasm-bindgen-cli --version "${VER_LOCK}" --locked
fi

# 3. compilar para wasm32 SIN los features nativos
echo "== cargo build $PERFIL --target wasm32-unknown-unknown --no-default-features --features wasm"
cargo build $PERFIL --target wasm32-unknown-unknown --no-default-features --features wasm

# 4. generar el paquete (glue JS + .wasm)
WASM="target/wasm32-unknown-unknown/release/lumen_mlight.wasm"
[ -n "$PERFIL" ] || WASM="target/wasm32-unknown-unknown/debug/lumen_mlight.wasm"
echo "== wasm-bindgen --target nodejs --out-dir pkg"
rm -rf pkg
wasm-bindgen --target nodejs --out-dir pkg "$WASM"

echo
echo "== listo: pkg/ ($(du -h pkg/lumen_mlight_bg.wasm 2>/dev/null | cut -f1) de wasm)"
echo "   comprobar: LUMEN_REPO=<repo> python test_wasm_vs_nativo.py"
