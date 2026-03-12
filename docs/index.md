# abicheck

**abicheck checks C/C++ library compatibility at both API and ABI levels.**

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
- 🔌 **ABICC drop-in** — full flag parity: `-lib`, `-old`, `-new`, `-s`, `-source`, `-skip-symbols`, `-v1/-v2`, `-stdout` and more ([reference](abicc_compat.md))
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
- [Verdicts](concepts/verdicts.md)
- [Exit Codes](exit_codes.md)
- [Migrating from ABICC](migration/from_abicc.md)
- [Using abicheck, Compatibility Modes, and Coverage](usage_and_coverage.md)
- [Examples Breakage Guide](examples_breakage_guide.md)
- [Tool Modes](tool_modes.md)
- [Tool Comparison: abicheck vs abidiff vs ABICC](tool_comparison.md)
- [Benchmark Report](benchmark_report.md)

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

`abicheck compare` uses: `0` (`NO_CHANGE`/`COMPATIBLE`), `2` (`API_BREAK`),
`4` (`BREAKING`).

For full CI-ready guidance (including `compat` mode and strict-mode behavior),
use the canonical reference: [Exit Codes](exit_codes.md).

## Status

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
