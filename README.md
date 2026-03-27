# abicheck

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/napetrov/abicheck/branch/main/graph/badge.svg)](https://codecov.io/gh/napetrov/abicheck)
[![PyPI version](https://img.shields.io/pypi/v/abicheck.svg)](https://pypi.org/project/abicheck/)
[![conda-forge](https://img.shields.io/conda/vn/conda-forge/abicheck.svg)](https://anaconda.org/conda-forge/abicheck)
[![Python versions](https://img.shields.io/pypi/pyversions/abicheck.svg)](https://pypi.org/project/abicheck/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**abicheck** is a command-line tool that detects breaking changes in C/C++ shared libraries before they reach production. It compares two versions of a shared library — along with their public headers — and reports whether existing binaries will continue to work or break at runtime.

Typical problems it catches: removed or renamed symbols, changed function signatures, struct layout drift, vtable reordering, enum value reassignment, and 114 other ABI/API incompatibilities that cause crashes, silent data corruption, or linker failures after a library upgrade.

> **Platforms:** Linux (ELF), Windows (PE/COFF), macOS (Mach-O). Binary metadata and header AST analysis on all platforms; debug info cross-check uses DWARF (Linux, macOS) and PDB (Windows).

---

## Installation

Install from PyPI:

```bash
pip install abicheck
```

Or with conda:

```bash
conda install -c conda-forge abicheck
```

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python >= 3.10** | All platforms |
| **`castxml`** | Clang-based C/C++ AST parser for header analysis (all platforms) |
| **`g++` or `clang++`** | Must be accessible to castxml |

`castxml` and a C++ compiler are required for header AST analysis. Without them, abicheck still works in **binary-only mode** (exports, imports, dependencies).

Ubuntu / Debian:

```bash
sudo apt install castxml g++
```

macOS:

```bash
brew install castxml
```

conda (all platforms):

```bash
conda install -c conda-forge castxml
```

### Naming note

This project (`napetrov/abicheck` on PyPI) is distinct from distro-packaged tools
with similar names (`abi-compliance-checker` wrappers in Debian `devscripts`, or
`abicheck` in Fedora's `libabigail-tools`). Run `abicheck --version` to confirm
which tool is active — it should show `abicheck X.Y.Z (napetrov/abicheck)`.

If the `abicheck` command conflicts with a distro tool, use:

```bash
python -m abicheck --version
python -m abicheck dump libfoo.so -H include/foo.h
```

### Install from source

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
```

Runtime only:

```bash
pip install -e .
```

With test and lint dependencies:

```bash
pip install -e ".[dev]"
```

---

## Quick start

### Compare two library versions

```bash
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h
```

Use `-H` when both versions share the same header:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

### Save a baseline snapshot, then compare against new builds

```bash
abicheck dump libfoo.so -H include/foo.h --version 1.0 -o baseline.json
```

```bash
abicheck compare baseline.json ./build/libfoo.so --new-header include/foo.h
```

### Output formats

Available formats: `markdown` (default), `json`, `sarif`, `html`.

```bash
abicheck compare old.so new.so -H foo.h --format json -o report.json
```

```bash
abicheck compare old.so new.so -H foo.h --format sarif -o report.sarif
```

```bash
abicheck compare old.so new.so -H foo.h --format html -o report.html
```

---

## Check application compatibility

Check whether your **application** (not just the library) is affected by a library update. Unlike `compare` (which shows all library changes), `appcompat` filters the diff to show only changes that affect the symbols your application actually uses.

Full check — does my app break with the new libfoo?

```bash
abicheck appcompat ./myapp libfoo.so.1 libfoo.so.2 -H include/foo.h
```

Quick check — does this library have all symbols my app needs?

```bash
abicheck appcompat ./myapp --check-against libfoo.so.2
```

See [Application Compatibility](https://napetrov.github.io/abicheck/user-guide/appcompat/) for full details.

---

## Full-stack dependency validation (Linux ELF)

Check whether a binary will load and run correctly in a given environment by resolving its full dependency tree, simulating symbol binding, and detecting ABI-breaking changes across all loaded DSOs.

Show dependency tree and symbol binding status:

```bash
abicheck deps /usr/bin/python3
```

Compare a binary's full stack across two sysroots:

```bash
abicheck stack-check usr/bin/myapp \
    --baseline /rootfs/v1 --candidate /rootfs/v2
```

Include dependency info in a regular compare:

```bash
abicheck compare old.so new.so -H foo.h --follow-deps
```

For the full CLI reference see the [documentation](https://napetrov.github.io/abicheck/getting-started/).

---

## Exit codes

Use these exit codes to gate CI pipelines. Non-zero exits can fail your build when breaking changes are detected.

### compare / compare-release

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `NO_CHANGE` / `COMPATIBLE` / `COMPATIBLE_WITH_RISK` | Safe — no binary ABI break |
| `1` | `SEVERITY_ERROR` | Severity-driven error (with `--severity-*` flags) |
| `2` | `API_BREAK` | Source-level break (recompile needed, binary may still work) |
| `4` | `BREAKING` | Binary ABI break (old binaries will crash or misbehave) |
| `8` | `REMOVED_LIBRARY` | Library removed in new version (compare-release only) |

### stack-check

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `PASS` | Binary loads and no harmful ABI changes |
| `1` | `WARN` | Binary loads but ABI risk in dependencies |
| `4` | `FAIL` | Load failure or ABI break in dependency stack |

### appcompat

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `COMPATIBLE` | App is not affected by the library change |
| `2` | `API_BREAK` | App uses changed API (recompile needed) |
| `4` | `BREAKING` | App will crash or misbehave with new library |

See the [full exit code reference](https://napetrov.github.io/abicheck/reference/exit-codes/) for CI gate patterns.

---

## GitHub Action

Basic usage:

```yaml
- uses: napetrov/abicheck@v1
  with:
    old-library: abi-baseline.json
    new-library: build/libfoo.so
    new-header: include/foo.h
```

With SARIF upload to GitHub Code Scanning:

```yaml
- uses: napetrov/abicheck@v1
  with:
    old-library: abi-baseline.json
    new-library: build/libfoo.so
    new-header: include/foo.h
    format: sarif
    upload-sarif: true
```

Fail on both ABI and API breaks:

```yaml
- uses: napetrov/abicheck@v1
  with:
    old-library: abi-baseline.json
    new-library: build/libfoo.so
    new-header: include/foo.h
    fail-on-breaking: true
    fail-on-api-break: true
```

Use the action's outputs to control downstream steps:

```yaml
- uses: napetrov/abicheck@v1
  id: abi
  with:
    old-library: abi-baseline.json
    new-library: build/libfoo.so
    new-header: include/foo.h

- run: echo "ABI verdict was ${{ steps.abi.outputs.verdict }}"
```

The action installs Python, castxml, and abicheck automatically. Available outputs: `verdict`, `exit-code`, `report-path`. See the [full GitHub Action documentation](https://napetrov.github.io/abicheck/user-guide/github-action/) for cross-compilation and matrix builds.

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

Use a custom YAML policy file for per-kind verdict overrides:

```bash
abicheck compare old.so new.so -H foo.h --policy-file my-policy.yaml
```

See [Policy Profiles](https://napetrov.github.io/abicheck/user-guide/policies/) for full details including YAML format.

---

## Suppression files

Suppress known or intentional changes so they don't fail CI:

```bash
abicheck compare old.so new.so -H foo.h --suppress suppressions.yaml
```

Example `suppressions.yaml`:

```yaml
version: 1

suppressions:
  # Exact symbol match
  - symbol: "_ZN3foo6Client10disconnectEv"
    change_kind: "func_removed"
    reason: "Client::disconnect() deprecated in v1.8, removed in v2.0"
    expires: "2026-09-01"

  # Pattern match — suppress all changes in internal namespaces
  - symbol_pattern: ".*N6detail.*"
    reason: "detail:: namespace is not part of public ABI"

  # All change kinds for a symbol
  - symbol: "_ZN3foo12LegacyHandleEv"
    reason: "LegacyHandle replaced by Handle alias — shim keeps compat"
    expires: "2026-12-31"
```

### Suppression lifecycle

Auto-generate candidate rules from a JSON diff, then enforce justification and expiry in CI:

```bash
# Generate candidates from a diff
abicheck compare old.so new.so -H foo.h --format json -o diff.json
abicheck suggest-suppressions diff.json -o candidates.yml

# Enforce in CI: require reasons and fail on expired rules
abicheck compare old.so new.so -H foo.h \
  --suppress suppressions.yaml \
  --strict-suppressions \
  --require-justification
```

| Flag | Effect |
|------|--------|
| `--strict-suppressions` | Fail if any suppression rule is past its `expires` date |
| `--require-justification` | Fail if any rule has an empty or missing `reason` field |

See [Suppressions](https://napetrov.github.io/abicheck/user-guide/suppressions/) for the full reference.

ABICC-format suppression files are also supported for easier migration. See [Migrating from ABICC](https://napetrov.github.io/abicheck/user-guide/from-abicc/) for details.

---

## ABICC drop-in replacement

If you're migrating from abi-compliance-checker, abicheck provides a compatibility CLI:

Before (ABICC):

```bash
abi-compliance-checker -lib libfoo -old old.xml -new new.xml -report-path r.html
```

After (abicheck — same flags):

```bash
abicheck compat check -lib libfoo -old old.xml -new new.xml -report-path r.html
```

See [Migrating from ABICC](https://napetrov.github.io/abicheck/user-guide/from-abicc/) for the full migration guide.

---

## Examples

The `examples/` directory contains **63 real-world ABI scenarios** — each with paired `v1`/`v2` source code and a consumer app that demonstrates the actual failure.

Build an example:

```bash
cd examples
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
```

```bash
cmake --build build --target case01_symbol_removal_v1 case01_symbol_removal_v2 --config Debug
```

Run abicheck on it:

```bash
abicheck compare build/case01_symbol_removal/libv1.so build/case01_symbol_removal/libv2.so \
    --old-header case01_symbol_removal/v1.h --new-header case01_symbol_removal/v2.h
```

Expected output verdict: `BREAKING — symbol 'helper' was removed`.

Covers: symbol removal, type/signature changes, struct layout, enums, vtables, qualifiers, templates, and more. See [Breaking Cases Catalog](https://napetrov.github.io/abicheck/concepts/breaking-cases-catalog/) and [ABI Breaks Explained](https://napetrov.github.io/abicheck/concepts/abi-breaks-explained/) for the full guide.

---

## Python API

abicheck can be used as a library for programmatic ABI checks:

```python
from pathlib import Path
from abicheck.service import run_compare

result, old_snapshot, new_snapshot = run_compare(
    old_input=Path("libfoo.so.1"),
    new_input=Path("libfoo.so.2"),
    old_headers=[Path("include/v1/foo.h")],
    new_headers=[Path("include/v2/foo.h")],
)

print(result.verdict)       # e.g. Verdict.BREAKING
print(len(result.changes))  # number of detected changes
```

`run_compare` also accepts optional parameters for includes, version labels, language (`"c++"` or `"c"`), suppression files, policy selection, and PDB paths. See `abicheck.service` for the full signature.

---

## Validation snapshot (abicheck)

All numbers below are computed on the **full 74-case catalog** (`01–73` + `26b`).

| Configuration | Cases | Exact verdict accuracy | False Positives* | False Negatives* |
|---|---:|---:|---:|---:|
| `abicheck compare` | 74 | **69/74 (93%)** | 0 | 1 |
| `abicheck compat` | 74 | **68/74 (92%)** | 0 | 1 |
| `abicheck strict` (`--strict-mode full`) | 74 | **61/74 (82%)** | 6 | 1 |
| `abidiff` | 74 | **23/74 (31%)** | 0 | 39 |
| `abidiff + headers` | 74 | **23/74 (31%)** | 0 | 39 |

\* FP/FN are for breaking-signal detection (`BREAKING` + `API_BREAK` treated as positive).

Source run:
- `python3 scripts/benchmark_comparison.py --tools abicheck abicheck_compat abicheck_strict abidiff abidiff_headers`

Per-case matrix and methodology:
- [Benchmark & Tool Comparison](https://napetrov.github.io/abicheck/reference/tool-comparison/)
- [examples/README.md](examples/README.md)

---

## Documentation

Full documentation is available at **[napetrov.github.io/abicheck](https://napetrov.github.io/abicheck/)**.

**Getting started:**
- [Installation & first check](https://napetrov.github.io/abicheck/getting-started/)
- [Exit codes reference](https://napetrov.github.io/abicheck/reference/exit-codes/)

**User guide:**
- [CLI Usage](https://napetrov.github.io/abicheck/user-guide/cli-usage/)
- [Application compatibility](https://napetrov.github.io/abicheck/user-guide/appcompat/) — check if your app breaks with a library update
- [Policy profiles](https://napetrov.github.io/abicheck/user-guide/policies/)
- [Output formats (SARIF, JSON, HTML)](https://napetrov.github.io/abicheck/user-guide/output-formats/)
- [GitHub Action](https://napetrov.github.io/abicheck/user-guide/github-action/)
- [Migrating from ABICC](https://napetrov.github.io/abicheck/user-guide/from-abicc/)
- [MCP Integration](https://napetrov.github.io/abicheck/user-guide/mcp-integration/)

**Concepts:**
- [Verdicts explained](https://napetrov.github.io/abicheck/concepts/verdicts/)
- [Architecture](https://napetrov.github.io/abicheck/concepts/architecture/)
- [Limitations](https://napetrov.github.io/abicheck/concepts/limitations/)
- [Troubleshooting](https://napetrov.github.io/abicheck/troubleshooting/)

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
