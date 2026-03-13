# abicheck

**abicheck** is a command-line tool that detects breaking changes in C/C++ shared libraries before they reach production. It compares two versions of a `.so` library — along with their public headers — and reports whether existing binaries will continue to work or break at runtime.

Typical problems it catches: removed or renamed symbols, changed function signatures, struct layout drift, vtable reordering, enum value reassignment, and dozens of other ABI/API incompatibilities that cause crashes, silent data corruption, or linker failures after a library upgrade.

> **Platform:** Linux (ELF binaries + DWARF debug info + C/C++ headers). Windows PE and macOS Mach-O are not yet supported.

## Features

- **Three-layer analysis** — ELF symbol table + Clang AST via castxml + DWARF cross-check for maximum accuracy
- **100% benchmark accuracy** — correct on all 42 test cases (vs 61% ABICC, 26% abidiff)
- **Multiple output formats** — Markdown, JSON, SARIF (GitHub Code Scanning), HTML
- **Policy profiles** — `strict_abi`, `sdk_vendor`, `plugin_abi`, or custom YAML overrides
- **ABICC drop-in** — full flag parity for migrating from abi-compliance-checker
- **CI-ready** — clear exit codes, SARIF upload, snapshot-based baselines

## Quick start

```bash
# Install (from source)
git clone https://github.com/napetrov/abicheck.git
cd abicheck && pip install -e .

# Compare two library versions
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h

# Or: save a baseline, compare later in CI
abicheck dump libfoo.so -H include/foo.h --version 1.0 -o baseline.json
abicheck compare baseline.json ./build/libfoo.so --new-header include/foo.h
```

## Exit codes

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `NO_CHANGE` or `COMPATIBLE` | Safe — no breaking changes |
| `1` | — | Tool/runtime error |
| `2` | `API_BREAK` | Source-level break (recompile needed, binary may work) |
| `4` | `BREAKING` | Binary ABI break (old binaries will crash or misbehave) |

## GitHub Actions

```yaml
- name: ABI check
  run: abicheck compare abi-baseline.json ./build/libfoo.so --new-header include/foo.h --format sarif -o abi.sarif

- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: abi.sarif
```

## Next steps

- [Getting Started](getting_started.md) — installation, first check, CI setup
- [Verdicts](concepts/verdicts.md) — NO_CHANGE / COMPATIBLE / API_BREAK / BREAKING
- [Exit Codes](exit_codes.md) — CI-ready exit code reference
- [Policy Profiles](policies.md) — built-in and custom policies
- [Examples & Breakage Guide](examples_breakage_guide.md) — 48 real-world ABI break scenarios
- [Benchmark & Tool Comparison](tool_comparison.md) — abicheck vs abidiff vs ABICC
- [ABICC Migration](migration/from_abicc.md) — migrating from abi-compliance-checker
- [Architecture](reference/architecture.md) — pipeline, modules, and design

## Status

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
