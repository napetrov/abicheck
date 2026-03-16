# abicheck

**abicheck** is a command-line tool that detects breaking changes in C/C++ shared libraries before they reach production. It compares two versions of a shared library — along with their public headers — and reports whether existing binaries will continue to work or break at runtime.

Typical problems it catches: removed or renamed symbols, changed function signatures, struct layout drift, vtable reordering, enum value reassignment, and dozens of other ABI/API incompatibilities that cause crashes, silent data corruption, or linker failures after a library upgrade.

> **Platforms:** Linux (ELF), Windows (PE/COFF), macOS (Mach-O). Binary metadata and header AST analysis on all platforms; debug info cross-check uses DWARF (Linux, macOS) with PDB support planned for Windows.

## Why abicheck

- **Three-layer analysis** — ELF symbol table + Clang AST (via castxml) + DWARF cross-check — catches changes that no single layer detects alone
- **100+ detection rules** — covers symbol removal, signature changes, struct/class layout drift, vtable reordering, enum value shifts, qualifier changes, and many more (see [Change Kind Reference](reference/change_kinds.md))
- **Multiple output formats** — Markdown, JSON, SARIF (GitHub Code Scanning), HTML
- **Policy profiles** — `strict_abi`, `sdk_vendor`, `plugin_abi`, or custom YAML overrides
- **ABICC drop-in** — full flag parity for migrating from abi-compliance-checker
- **CI-ready** — clear exit codes, SARIF upload, snapshot-based baselines

## Quick start

```bash
# Install
git clone https://github.com/napetrov/abicheck.git
cd abicheck && pip install -e .

# Compare two library versions
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h
```

## Exit codes (`abicheck compare`)

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `NO_CHANGE` / `COMPATIBLE` | Safe — no breaking changes |
| `1` | — | Tool/runtime error |
| `2` | `API_BREAK` | Source-level API break (recompile needed, binary still works) |
| `4` | `BREAKING` | Binary ABI break (old binaries will crash or misbehave) |

> `abicheck compat` uses ABICC-compatible exit codes (1 = BREAKING, 2 = API_BREAK). See [Exit Codes](exit_codes.md) for details.

## CI integration

Save a baseline at release time, compare every new build:

```yaml
- name: Compare ABI
  run: |
    abicheck compare abi-baseline.json ./build/libfoo.so \
      --new-header include/foo.h --format sarif -o abi.sarif

- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: abi.sarif
```

## Next steps

- [Getting Started](getting_started.md) — installation, first check, CI setup
- [Platform Support](platforms.md) — Linux/macOS/Windows host matrix, cross-platform scanning
- [Verdicts](concepts/verdicts.md) — what each verdict means and how to handle it
- [Examples & Breakage Guide](examples_breakage_guide.md) — real-world ABI/API break scenarios with code
- [Change Kind Reference](reference/change_kinds.md) — full list of 100+ detected change types
- [Policy Profiles](policies.md) — built-in and custom policies
- [ABICC Compatibility](abicc_compat.md) — drop-in replacement and migration from abi-compliance-checker
- [MCP Server (Agent Integration)](mcp.md) — use abicheck from AI agents via MCP
- [Benchmark & Tool Comparison](tool_comparison.md) — abicheck vs abidiff vs ABICC

## Status

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
