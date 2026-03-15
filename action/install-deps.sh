#!/usr/bin/env bash
# Install system dependencies (castxml + C/C++ compiler) for abicheck.
# Called by the composite action when install-deps=true.
set -euo pipefail

echo "::group::Install system dependencies for abicheck"

OS="$(uname -s)"
case "$OS" in
  Linux)
    sudo apt-get update -qq
    sudo apt-get install -y -qq castxml gcc g++ > /dev/null
    ;;
  Darwin)
    # macOS: castxml via Homebrew, clang is pre-installed via Xcode
    if ! command -v castxml &> /dev/null; then
      brew install castxml
    fi
    ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    echo "::warning::Windows dependency installation is not automated."
    echo "Please ensure castxml and a C++ compiler are on PATH."
    echo "See: https://github.com/CastXML/CastXML/releases"
    ;;
  *)
    echo "::warning::Unknown OS '$OS'. Skipping dependency installation."
    ;;
esac

echo "::endgroup::"

# Verify castxml is available
if command -v castxml &> /dev/null; then
  echo "castxml version: $(castxml --version 2>&1 | head -1)"
else
  echo "::warning::castxml not found. Header analysis will not be available."
  echo "Binary-only mode (exports/imports) will still work."
fi
