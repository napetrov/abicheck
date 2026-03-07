# abicheck

**ABI compatibility checker for shared libraries.**

Drop-in replacement for [ABICC](https://lvc.github.io/abi-compliance-checker/) with modern Python API, JSON/SARIF output, and GitHub Actions integration.

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
