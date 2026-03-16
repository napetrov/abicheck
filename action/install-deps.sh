#!/usr/bin/env bash
# Install system dependencies (castxml + C/C++ compiler) for abicheck.
# Called by the composite action when install-deps=true.
set -euo pipefail

echo "::group::Install system dependencies for abicheck"

OS="$(uname -s)"
case "$OS" in
  Linux)
    if ! command -v apt-get &> /dev/null; then
      echo "::warning::apt-get not found. Skipping automatic dependency installation on Linux."
      echo "Please ensure castxml and a C++ compiler are installed manually."
    elif ! command -v sudo &> /dev/null; then
      echo "::warning::sudo not found. Skipping automatic dependency installation."
      echo "Please ensure castxml and a C++ compiler are installed manually."
    else
      sudo apt-get update -qq
      sudo apt-get install -y -qq castxml gcc g++ > /dev/null
    fi
    ;;
  Darwin)
    # macOS: castxml via Homebrew, clang is pre-installed via Xcode
    if ! command -v brew &> /dev/null; then
      echo "::warning::Homebrew not found. Skipping automatic castxml installation on macOS."
      echo "Please install castxml manually: https://github.com/CastXML/CastXML/releases"
    elif ! command -v castxml &> /dev/null; then
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
