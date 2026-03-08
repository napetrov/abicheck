# abicheck

**abicheck is an ABI compatibility checker for C/C++ API and ABI compatibility.**

It is designed as a drop-in replacement for
[ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/),
with modern CLI ergonomics, Python integration, and machine-readable reports.

This project is inspired by:

- [libabigail / abidiff](https://sourceware.org/libabigail/)
- [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/)

Both projects made ABI tooling possible for many teams; thank you to their authors
and maintainers. abicheck exists to provide an actively extensible path where teams
can continue evolving ABI checks in modern CI environments.

## Features

- 🔍 **Deep analysis** — struct layout, vtable, enum values, calling conventions, symbol visibility
- 📄 **SARIF output** — native GitHub Code Scanning integration
- 🔌 **ABICC-compatible** — same XML descriptor format (`-lib`, `-old`, `-new` CLI flags)
- 🐍 **Python API** — import and use programmatically
- ⚡ **Fast** — no DWARF required for header-based analysis

## Quick start

```bash
pip install abicheck

# Dump ABI snapshots
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o libfoo-2.0.json

# Compare
abicheck compare libfoo-1.0.json libfoo-2.0.json
```

## Next steps

- [Getting Started](getting_started.md)
- [Using abicheck, Compatibility Modes, and Coverage](usage_and_coverage.md)
- [Tool Modes](tool_modes.md)

## GitHub Actions

```yaml
- name: Check ABI
  run: |
    abicheck compare old.json new.json --format sarif -o abi.sarif

- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: abi.sarif
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | No ABI changes |
| 1 | Compatible changes only |
| 4 | Breaking ABI changes detected |

## Status

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
