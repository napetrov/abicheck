#!/usr/bin/env bash
# fetch_public_libs.sh — Download conda-forge packages for stress testing
#
# Usage:
#   bash scripts/fetch_public_libs.sh [--dest /tmp/ac_run] [--platform linux-64]
#
# Requirements: conda (or mamba/micromamba) available in PATH
# Each package is unpacked into: <dest>/<name>_<version>/lib/

set -euo pipefail

DEST="${DEST:-/tmp/ac_run}"
PLATFORM="${PLATFORM:-linux-64}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest)     DEST="$2";     shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$DEST"

# Packages to fetch: "name version" pairs
# Extend this list as needed
PACKAGES=(
  # abseil
  "libabseil 20240116.0"
  "libabseil 20240116.1"
  "libabseil 20240116.2"
  "libabseil 20240722.0"
  "libabseil 20250127.0"
  # openssl
  "openssl 1.1.1s"
  "openssl 1.1.1t"
  "openssl 3.3.1"
  "openssl 3.3.2"
  "openssl 3.4.0"
  "openssl 3.4.1"
  "openssl 3.5.0"
  "openssl 3.5.1"
  "openssl 3.5.2"
  # libcurl
  "libcurl 7.88.1"
  "libcurl 8.0.1"
  "libcurl 8.11.1"
  "libcurl 8.12.0"
  "libcurl 8.13.0"
  "libcurl 8.14.0"
  "libcurl 8.14.1"
  "libcurl 8.17.0"
  "libcurl 8.18.0"
  # libpng
  "libpng 1.6.43"
  "libpng 1.6.44"
  # zlib
  "zlib 1.3.0"
  "zlib 1.3.1"
  # libxml2
  "libxml2 2.12.0"
  "libxml2 2.12.6"
  "libxml2 2.12.7"
  "libxml2 2.13.4"
  "libxml2 2.13.5"
  # zstd
  "zstd 1.5.5"
  "zstd 1.5.6"
  # snappy
  "snappy 1.1.9"
  "snappy 1.2.0"
  "snappy 1.2.1"
  # libjpeg-turbo
  "libjpeg-turbo 2.1.5"
  "libjpeg-turbo 3.0.0"
  "libjpeg-turbo 3.1.0"
  # libwebp
  "libwebp 1.3.0"
  "libwebp 1.4.0"
  "libwebp 1.5.0"
  # libopenblas
  "libopenblas 0.3.28"
  "libopenblas 0.3.29"
  "libopenblas 0.3.30"
  # re2
  "re2 2023.09.01"
  "re2 2024.07.02"
  # libevent
  "libevent 2.1.10"
  "libevent 2.1.12"
  # gmp
  "gmp 6.2.1"
  "gmp 6.3.0"
  # libsqlite
  "libsqlite 3.46.0"
  "libsqlite 3.47.0"
  "libsqlite 3.48.0"
)

CONDA_CMD="conda"
if command -v mamba &>/dev/null;      then CONDA_CMD="mamba"; fi
if command -v micromamba &>/dev/null; then CONDA_CMD="micromamba"; fi

echo "📦 Fetching ${#PACKAGES[@]} package versions into $DEST"
echo "   Platform: $PLATFORM   Tool: $CONDA_CMD"
echo ""

FAILED=()
for entry in "${PACKAGES[@]}"; do
  PKG="${entry%% *}"
  VER="${entry#* }"
  DIR="$DEST/${PKG}_${VER}"

  if [[ -d "$DIR/lib" ]]; then
    echo "  ✓ already have ${PKG}_${VER}"
    continue
  fi

  TMP=$(mktemp -d)
  echo -n "  ↓ ${PKG} ${VER} ... "
  if $CONDA_CMD install -y --prefix "$TMP" --channel conda-forge \
      --platform "$PLATFORM" --no-deps "${PKG}==${VER}" &>/dev/null 2>&1; then
    mkdir -p "$DIR"
    # copy lib/ and include/ if present
    [[ -d "$TMP/lib" ]]     && cp -r "$TMP/lib"     "$DIR/"
    [[ -d "$TMP/include" ]] && cp -r "$TMP/include"  "$DIR/"
    echo "✅"
  else
    echo "❌ FAILED (package not found or version mismatch)"
    FAILED+=("${PKG}==${VER}")
  fi
  rm -rf "$TMP"
done

echo ""
echo "Done. Output: $DEST"
if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo ""
  echo "⚠ Failed packages (${#FAILED[@]}):"
  for f in "${FAILED[@]}"; do echo "  - $f"; done
  exit 1
fi
