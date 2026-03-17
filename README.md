# abicheck

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/napetrov/abicheck/branch/main/graph/badge.svg)](https://codecov.io/gh/napetrov/abicheck)
[![PyPI version](https://img.shields.io/pypi/v/abicheck.svg)](https://pypi.org/project/abicheck/)
[![conda-forge](https://img.shields.io/conda/vn/conda-forge/abicheck.svg)](https://anaconda.org/conda-forge/abicheck)
[![Python versions](https://img.shields.io/pypi/pyversions/abicheck.svg)](https://pypi.org/project/abicheck/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**abicheck** is a command-line tool that detects breaking changes in C/C++ shared libraries before they reach production. It compares two versions of a shared library — along with their public headers — and reports whether existing binaries will continue to work or break at runtime.

Typical problems it catches: removed or renamed symbols, changed function signatures, struct layout drift, vtable reordering, enum value reassignment, and dozens of other ABI/API incompatibilities that cause crashes, silent data corruption, or linker failures after a library upgrade.

> **Platforms:** Linux (ELF), Windows (PE/COFF), macOS (Mach-O). Binary metadata and header AST analysis on all platforms; debug info cross-check uses DWARF (Linux, macOS) and PDB (Windows).

---

## Installation

```bash
pip install abicheck
# or
conda install -c conda-forge abicheck
```

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python >= 3.10** | All platforms |
| **`castxml`** | Clang-based C/C++ AST parser for header analysis (all platforms) |
| **`g++` or `clang++`** | Must be accessible to castxml |

`castxml` and a C++ compiler are required for header AST analysis. Without them, abicheck still works in binary-only mode (exports, imports, dependencies).

```bash
# Ubuntu / Debian
sudo apt install castxml g++

# macOS
brew install castxml

# conda (all platforms)
conda install -c conda-forge castxml
```

### Install from source

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e .          # runtime only
pip install -e ".[dev]"   # with test & lint dependencies
```

---

## Quick start

```bash
# Compare two library versions
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h

# Same header for both versions
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h

# Save baseline snapshot, then compare against new builds
abicheck dump libfoo.so -H include/foo.h --version 1.0 -o baseline.json
abicheck compare baseline.json ./build/libfoo.so --new-header include/foo.h
```

Output formats: `markdown` (default), `json`, `sarif`, `html`. Use `--format` and `-o` to select.

### Full-stack dependency validation (Linux ELF)

Check whether a binary will load and run correctly in a given environment by
resolving its full dependency tree, simulating symbol binding, and detecting
ABI-breaking changes across all loaded DSOs:

```bash
# Show dependency tree + symbol binding status for a binary
abicheck deps /usr/bin/python3

# Compare a binary's full stack across two sysroots
abicheck stack-check usr/bin/myapp \
    --baseline /rootfs/v1 --candidate /rootfs/v2

# Include dependency info in a regular compare
abicheck compare old.so new.so -H foo.h --follow-deps
```

For the full CLI reference see the [documentation](https://napetrov.github.io/abicheck/getting-started/).

---

## Exit codes

**compare:**

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK` | Safe — no binary ABI break |
| `1` | — | Tool/runtime error (or `ADDITIONS` with `--fail-on-additions`) |
| `2` | `API_BREAK` | Source-level break (recompile needed, binary may work) |
| `4` | `BREAKING` | Binary ABI break (old binaries will crash or misbehave) |

**stack-check:**

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `PASS` | Binary loads and no harmful ABI changes |
| `1` | `WARN` | Binary loads but ABI risk in dependencies |
| `4` | `FAIL` | Load failure or ABI break in dependency stack |

See the [full exit code reference](https://napetrov.github.io/abicheck/reference/exit-codes/) for `deps`, `compat`, and CI gate patterns.

---

## GitHub Action

```yaml
- uses: napetrov/abicheck@v1
  with:
    old-library: abi-baseline.json
    new-library: build/libfoo.so
    new-header: include/foo.h
```

The action installs Python, castxml, and abicheck automatically. See the [full GitHub Action documentation](https://napetrov.github.io/abicheck/user-guide/github-action/) for SARIF integration, cross-compilation, and matrix builds.

---

## Policy profiles

Policies control how detected changes are classified. A change that is `BREAKING` under `strict_abi` might be downgraded to `COMPATIBLE` under `sdk_vendor`.

| Profile | Use case |
|---------|----------|
| `strict_abi` (default) | System libraries, public SDKs |
| `sdk_vendor` | Vendor SDKs, optional extensions |
| `plugin_abi` | Plugins rebuilt with host |

```bash
abicheck compare old.so new.so -H foo.h --policy sdk_vendor
```

Custom YAML overrides are also supported. See [Policy Profiles](https://napetrov.github.io/abicheck/user-guide/policies/) for full details.

---

## ABICC drop-in replacement

```bash
# Before (ABICC):
abi-compliance-checker -lib libfoo -old old.xml -new new.xml -report-path r.html

# After (abicheck — same flags):
abicheck compat check -lib libfoo -old old.xml -new new.xml -report-path r.html
```

See [Migrating from ABICC](https://napetrov.github.io/abicheck/user-guide/from-abicc/) for the full migration guide.

---

## Examples

The `examples/` directory contains **63 real-world ABI scenarios** — each with paired `v1`/`v2` source code and a consumer app that demonstrates the actual failure.

```bash
cd examples
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build --target case01_symbol_removal_v1 case01_symbol_removal_v2 --config Debug

abicheck compare build/case01_symbol_removal/libv1.so build/case01_symbol_removal/libv2.so \
    --old-header case01_symbol_removal/v1.h --new-header case01_symbol_removal/v2.h
# Verdict: BREAKING — symbol 'helper' was removed
```

Covers: symbol removal, type/signature changes, struct layout, enums, vtables, qualifiers, templates, and more. See [Breaking Cases Catalog](https://napetrov.github.io/abicheck/concepts/breaking-cases-catalog/) and [ABI Breaks Explained](https://napetrov.github.io/abicheck/concepts/abi-breaks-explained/) for the full guide.

---

## Documentation

Full documentation is available at **[napetrov.github.io/abicheck](https://napetrov.github.io/abicheck/)**.

**Getting started:**
- [Installation & first check](https://napetrov.github.io/abicheck/getting-started/)
- [Exit codes reference](https://napetrov.github.io/abicheck/reference/exit-codes/)

**Concepts:**
- [Verdicts explained](https://napetrov.github.io/abicheck/concepts/verdicts/)
- [Architecture](https://napetrov.github.io/abicheck/concepts/architecture/)
- [Limitations](https://napetrov.github.io/abicheck/concepts/limitations/)
- [Troubleshooting](https://napetrov.github.io/abicheck/troubleshooting/)

**User guide:**
- [CLI Usage](https://napetrov.github.io/abicheck/user-guide/cli-usage/)
- [Policy profiles](https://napetrov.github.io/abicheck/user-guide/policies/)
- [Output formats (SARIF, JSON, HTML)](https://napetrov.github.io/abicheck/user-guide/output-formats/)
- [GitHub Action](https://napetrov.github.io/abicheck/user-guide/github-action/)
- [Migrating from ABICC](https://napetrov.github.io/abicheck/user-guide/from-abicc/)
- [MCP Integration](https://napetrov.github.io/abicheck/user-guide/mcp-integration/)

**Reference:**
- [Change kind reference](https://napetrov.github.io/abicheck/reference/change-kinds/)
- [Tool comparison & benchmarks](https://napetrov.github.io/abicheck/reference/tool-comparison/)
- [Platform support](https://napetrov.github.io/abicheck/reference/platforms/)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, testing, code style, and PR workflow.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

Copyright 2026 Nikolay Petrov
