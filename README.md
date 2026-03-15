# abicheck

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/napetrov/abicheck/branch/main/graph/badge.svg)](https://codecov.io/gh/napetrov/abicheck)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**abicheck** is a command-line tool that detects breaking changes in C/C++ shared libraries before they reach production. It compares two versions of a shared library — along with their public headers — and reports whether existing binaries will continue to work or break at runtime.

Typical problems it catches: removed or renamed symbols, changed function signatures, struct layout drift, vtable reordering, enum value reassignment, and dozens of other ABI/API incompatibilities that cause crashes, silent data corruption, or linker failures after a library upgrade.

> **Platforms:** Linux (ELF), Windows (PE/COFF), macOS (Mach-O). Binary metadata and header AST analysis on all platforms; debug info cross-check uses DWARF (Linux, macOS) with PDB support planned for Windows.

---

## Installation

> **Note:** abicheck is not yet published to PyPI or conda-forge. Install from source for now.

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python >= 3.10** | All platforms |
| **`castxml`** | Clang-based C/C++ AST parser for header analysis (all platforms) |
| **`g++` or `clang++`** | Must be accessible to castxml |

`castxml` and a C++ compiler are required for header AST analysis. Without them, abicheck still works in binary-only mode (exports, imports, dependencies). castxml is available on all platforms via conda-forge or system packages.

```bash
# Ubuntu / Debian
sudo apt install castxml g++
```

```bash
# macOS
brew install castxml
```

```bash
# conda (all platforms)
conda install -c conda-forge castxml
```

```bash
# Windows — install castxml from https://github.com/CastXML/CastXML/releases
# and ensure it is on PATH, along with a C++ compiler (MSVC or MinGW g++)
```

### Install from source

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e .
```

For development (includes test & lint dependencies):

```bash
pip install -e ".[dev]"
```

---

## Quick start

### Compare two library versions

The simplest way to check ABI compatibility — pass two `.so` files and their public headers:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h
```

If the header file is the same for both versions, use the shorthand:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

### Use saved snapshots (for CI baselines)

Save an ABI snapshot once per release, then compare against new builds:

```bash
# Save baseline
abicheck dump libfoo.so -H include/foo.h --version 1.0 -o baseline.json
```

```bash
# Compare new build against saved baseline
abicheck compare baseline.json ./build/libfoo.so --new-header include/foo.h
```

### Key flags

| Flag | Description |
|------|-------------|
| `--old-header` / `--new-header` | Public headers for each version |
| `-H` | Same header for both versions (shorthand) |
| `--format` | Output format: `markdown` (default), `json`, `sarif`, `html` |
| `-o` | Write report to file |
| `--policy` | Verdict policy: `strict_abi` (default), `sdk_vendor`, `plugin_abi` |
| `--policy-file` | Custom YAML policy overrides |
| `--lang` | Language mode: `c++` (default) or `c` |
| `-v` / `--verbose` | Debug output |

For full CLI reference and advanced options (cross-compilation, suppression files, symbol filtering), see the [documentation](https://napetrov.github.io/abicheck/getting_started/).

---

## Output formats and reports

abicheck supports four output formats:

```bash
# Markdown (default) — human-readable, printed to stdout
abicheck compare old.so new.so -H foo.h
```

```bash
# JSON — machine-readable, includes precise verdict field for CI parsing
abicheck compare old.so new.so -H foo.h --format json -o result.json
```

```bash
# SARIF — for GitHub Code Scanning integration
abicheck compare old.so new.so -H foo.h --format sarif -o abi.sarif
```

```bash
# HTML — standalone report for review
abicheck compare old.so new.so -H foo.h --format html -o report.html
```

### Example report (markdown output)

```text
# ABI Report: libfoo.so

| | |
|---|---|
| **Old version** | `1.0` |
| **New version** | `2.0` |
| **Verdict** | ❌ `BREAKING` |
| Breaking changes | 2 |
| Source-level breaks | 0 |
| Deployment risk changes | 0 |
| Compatible additions | 1 |

## ❌ Breaking Changes

- **func_removed**: Public function removed: helper (`helper`)
  > Old binaries call a symbol that no longer exists; dynamic linker will refuse to load or crash at call site.

- **type_size_changed**: Size changed: Point (64 → 96 bits) (`64` → `96`)
  > Old code allocates or copies the type with the old size; heap/stack corruption, out-of-bounds access.

## ✅ Compatible Additions

- Field added: Point::z

---
## Legend

| Verdict | Meaning |
|---------|---------|
| ✅ NO_CHANGE | Identical ABI |
| ✅ COMPATIBLE | Only additions (backward compatible) |
| ⚠️ COMPATIBLE_WITH_RISK | Binary-compatible; verify target environment |
| ⚠️ API_BREAK | Source-level API change — recompilation required |
| ❌ BREAKING | Binary ABI break — recompilation required |

_Generated by [abicheck](https://github.com/napetrov/abicheck)_
```

---

## Policy profiles

Policies control how detected changes are classified. A change that is `BREAKING` under `strict_abi` might be downgraded to `COMPATIBLE` under `sdk_vendor`.

**Built-in profiles:**

| Profile | Use case | Behavior |
|---------|----------|----------|
| `strict_abi` (default) | System libraries, public SDKs | Every ABI change at maximum severity |
| `sdk_vendor` | Vendor SDKs, optional extensions | Source-only changes (renames, access) downgraded to COMPATIBLE |
| `plugin_abi` | Plugins rebuilt with host | Calling-convention changes downgraded to COMPATIBLE |

```bash
abicheck compare old.so new.so -H foo.h --policy sdk_vendor
```

### Custom policy file

Create a YAML file to override classification of specific change kinds:

```yaml
base_policy: strict_abi
overrides:
  enum_member_renamed: ignore   # break | warn | ignore
  field_renamed: ignore
```

```bash
abicheck compare old.so new.so -H foo.h --policy-file project_policy.yaml
```

Semantics: `break` = BREAKING (exit 4), `warn` = API_BREAK (exit 2), `ignore` = COMPATIBLE (exit 0). Kinds not listed in `overrides` use the `base_policy`.

See [Policy Profiles](https://napetrov.github.io/abicheck/policies/) for full details.

---

## Exit codes

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK` | Safe — no binary ABI break (risk report may have warnings) |
| `1` | — | Tool/runtime error |
| `2` | `API_BREAK` | Source-level break (recompile needed, binary may work) |
| `4` | `BREAKING` | Binary ABI break (old binaries will crash or misbehave) |

Use exit codes directly in CI gates. For precise verdicts, parse `--format json` output.

---

## GitHub Actions integration

A typical CI flow: dump the ABI snapshot once at release time, then compare every new build against that saved baseline.

```yaml
name: ABI check
on: [push, pull_request]

jobs:
  abi-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install abicheck
        run: pip install git+https://github.com/napetrov/abicheck.git

      # ── Release step (run once when cutting a release) ─────────────
      # Dump the ABI baseline and upload it as a release artifact:
      #
      #   abicheck dump ./build/libfoo.so -H include/foo.h \
      #     --version ${{ github.ref_name }} -o abi-baseline.json
      #
      # Then download it in CI (e.g. from a release asset or artifact).

      - name: Download ABI baseline
        uses: actions/download-artifact@v4
        with:
          name: abi-baseline
          # abi-baseline.json saved from the last release

      - name: Build current library
        run: make -C src/   # produces ./build/libfoo.so

      # ── CI step: compare new build against saved baseline ──────────
      - name: Compare ABI
        run: |
          abicheck compare abi-baseline.json ./build/libfoo.so \
            --new-header include/foo.h \
            --format sarif -o abi.sarif

      - uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: abi.sarif
```

Exit codes for CI gates: `0` = compatible, `1` = tool error, `2` = API break, `4` = breaking ABI change.

---

## ABICC drop-in replacement

For teams migrating from [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/) — swap one command, keep your existing XML descriptors:

```bash
# Before (ABICC):
abi-compliance-checker -lib libfoo -old old.xml -new new.xml -report-path r.html
```

```bash
# After (abicheck — same flags):
abicheck compat check -lib libfoo -old old.xml -new new.xml -report-path r.html
```

When ready, migrate to the simpler native workflow:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

See [ABICC Migration Guide](https://napetrov.github.io/abicheck/migration/from_abicc/) for full flag reference, exit code differences, and migration checklist.

---

## Examples and ABI breakage catalog

The `examples/` directory contains **48 real-world ABI break scenarios** — each with paired `v1`/`v2` source code, a consumer app that demonstrates the actual failure, and a CMakeLists.txt to build it on Linux, macOS, and Windows.

### Try an example

```bash
cd examples
cmake -S . -B build -DCMAKE_BUILD_TYPE=Debug
cmake --build build --target case01_symbol_removal_v1 case01_symbol_removal_v2
abicheck compare build/case01_symbol_removal/libv1.so build/case01_symbol_removal/libv2.so \
    --old-header case01_symbol_removal/v1.h --new-header case01_symbol_removal/v2.h
# Verdict: BREAKING — symbol 'helper' was removed
```

### What the examples cover

**Breaking changes** — changes that crash or corrupt existing binaries:

| Category | Cases | Examples |
|----------|-------|---------|
| Symbol removal / rename | 01, 12 | Function removed from export table |
| Type/signature changes | 02, 10, 33 | Parameter type, return type, pointer level changed |
| Struct/class layout | 07, 14, 40, 43, 44 | Field added/reordered, class size changed |
| Enum changes | 08, 19, 20 | Value reassigned, member removed |
| C++ vtable / virtual | 09, 23, 38 | Vtable reorder, pure virtual added |
| Qualifiers / binding | 21, 22, 30, 39 | Method became static, const changed |
| Templates / typedefs | 17, 28, 45, 46, 48 | Template layout, typedef opaque |
| Complex types | 24, 26, 35, 36, 37 | Union field removed, field renamed, base class changed |

**Compatible changes** — safe, no binary break:

| Cases | Examples |
|-------|---------|
| 03, 25, 26b | New symbol added, enum member appended, union in reserved space |
| 04, 32 | No change, parameter defaults changed |
| 05, 06 | SONAME policy, visibility leak (bad practice but binary-safe) |
| 13, 27, 29, 47 | Symbol versioning, weak binding, IFUNC, inline-to-outlined |
| 16 | Inline to non-inline (ODR concern, not binary break) |

**API-only breaks** — source-level break, binary still works:

| Cases | Examples |
|-------|---------|
| 31, 34 | Enum renamed, access level changed |

### Benchmarks

abicheck detects 100+ change types across ELF, AST, and DWARF layers. The `examples/` directory contains 48 representative test cases with expected verdicts in `examples/ground_truth.json`. Cross-tool comparison on 42 of these cases:

| Tool | Correct / Scored | Accuracy |
|------|-----------------|----------|
| **abicheck (compare)** | **42/42** | **100%** |
| abicheck (compat) | 40/42 | 95% |
| ABICC (xml) | 25/41 | 61% |
| ABICC (abi-dumper) | 20/30 | 66% |
| abidiff | 11/42 | 26% |

abicheck passes all 48 cases. Run `python3 scripts/benchmark_comparison.py` to reproduce.

See [Benchmark & Tool Comparison](https://napetrov.github.io/abicheck/tool_comparison/) for per-case results, methodology, and timing data.

---

## ABI compatibility guide

Understanding what breaks ABI and what doesn't is essential for library maintainers. Here is a quick reference:

### Changes that break binary compatibility

- **Removing or renaming** an exported function or variable
- **Changing function signature** — parameter types, return type, calling convention
- **Modifying struct/class layout** — adding/removing/reordering fields, changing field types
- **Changing enum values** — reassigning numeric values, removing members
- **C++ vtable changes** — reordering virtual methods, adding pure virtuals
- **Changing method qualifiers** — `const`, `static`, `noexcept` (when it affects mangling)
- **Changing global variable type** — size/alignment mismatch

### Changes that are safe (binary compatible)

- **Adding** new exported functions or variables
- **Adding** new enum members at the end (without shifting existing values)
- **Weakening** symbol binding (GLOBAL to WEAK)
- **Adding** IFUNC resolvers
- **Adding** symbol version tags

### Best practices for library maintainers

1. **Treat public headers as ABI contracts** — any change is potentially breaking
2. **Use SONAME versioning** — bump major version on incompatible changes
3. **Hide implementation details** — use Pimpl pattern, opaque handles, `-fvisibility=hidden`
4. **Add, don't modify** — introduce `foo_v2()` instead of changing `foo()`
5. **Freeze enum values** — never renumber released constants
6. **Don't expose third-party types** in public API — wrap them behind stable project-owned types

See [Examples Breakage Guide](https://napetrov.github.io/abicheck/examples_breakage_guide/) for detailed code examples and failure demonstrations for each case.

---

## Architecture

abicheck supports three binary formats, each with a dedicated metadata parser:

```text
                    ┌─────────────────────────────────────────────┐
                    │                abicheck CLI                  │
                    │      dump · compare · compat check/dump     │
                    └──────────┬──────────────┬───────────────────┘
                               │              │
                    ┌──────────▼──────────┐   │
                    │   Format detection  │   │
                    │  (ELF / PE / Mach-O)│   │
                    └──┬──────┬───────┬───┘   │
                       │      │       │       │
              ┌────────▼┐ ┌───▼────┐ ┌▼───────▼──┐
              │   ELF   │ │   PE   │ │  Mach-O   │
              │ pyelftools│ │ pefile │ │ macholib  │
              └────┬────┘ └───┬────┘ └─────┬─────┘
                   │          │            │
              ┌────▼──────────▼────────────▼─────┐
              │        Snapshot (JSON model)       │
              └────────────────┬──────────────────┘
                               │
              ┌────────────────▼──────────────────┐
              │  Header AST (castxml) — all platforms│
              └────────────────┬──────────────────┘
                               │
              ┌────────────────▼──────────────────┐
              │ Debug info cross-check             │
              │  DWARF (Linux, macOS) │ PDB (Win)  │
              └────────────────┬──────────────────┘
                               │
              ┌────────────────▼──────────────────┐
              │    Checker → Changes → Verdict     │
              └───────────────────────────────────┘
```

### Analysis layers

| Layer | Technology | Linux (ELF) | Windows (PE) | macOS (Mach-O) |
|-------|-----------|:-----:|:-------:|:-----:|
| **Binary metadata** | pyelftools / pefile / macholib | Yes | Yes | Yes |
| **Header AST** | castxml (Clang) | Yes | Yes | Yes |
| **Debug info cross-check** | DWARF (pyelftools) / PDB | Yes (DWARF) | Planned (PDB) | Yes (DWARF) |

All three layers combine for maximum accuracy. castxml is cross-platform (provided by Kitware for Linux, Windows, and macOS), so header AST analysis works everywhere. Debug info cross-check currently uses DWARF (Linux and macOS); PDB support for Windows is planned.

### castxml compiler support

castxml uses an internal Clang compiler for parsing but can emulate the preprocessor and target platform of an external compiler via `--castxml-cc-<id>`:

| Compiler ID | Compiler | Platforms |
|-------------|----------|-----------|
| `gnu` | GCC / g++ | Linux, macOS, Windows (MinGW) |
| `gnu-c` | GCC / gcc (C mode) | Linux, macOS, Windows (MinGW) |
| `msvc` | Microsoft Visual C++ (cl) | Windows |
| `msvc-c` | Microsoft Visual C (cl, C mode) | Windows |

abicheck auto-detects the compiler mode: if the compiler binary is `cl` or `cl.exe`, it uses `--castxml-cc-msvc`; otherwise it uses `--castxml-cc-gnu`. You can override the compiler via `--gcc-path`:

```bash
# Use a specific GCC
abicheck dump libfoo.so -H foo.h --gcc-path /usr/bin/g++-12

# Use MSVC on Windows
abicheck dump foo.dll -H foo.h --gcc-path cl

# Use MinGW on Windows
abicheck dump foo.dll -H foo.h --gcc-path x86_64-w64-mingw32-g++
```

### Python dependencies

| Package | Role | Platforms |
|---------|------|-----------|
| `pyelftools` | ELF/DWARF parsing | Linux |
| `pefile` | PE/COFF parsing (`.dll`, `.exe`) | All (pure Python) |
| `macholib` | Mach-O parsing (`.dylib`, `.framework`) | All (pure Python) |
| `click` | CLI framework | All |
| `pyyaml` | YAML policy file parsing | All |
| `defusedxml` | Safe XML parsing (castxml output) | All |
| `packaging` | Version comparison | All |

### Key modules

| Module | Responsibility |
|--------|---------------|
| `cli.py` | CLI entrypoint (`dump`, `compare`, `compat check/dump`) |
| `dumper.py` | Snapshot generation from `.so` + headers |
| `elf_metadata.py` | ELF binary parser (Linux `.so`) |
| `pe_metadata.py` | PE binary parser (Windows `.dll`) |
| `macho_metadata.py` | Mach-O binary parser (macOS `.dylib`) |
| `checker.py` | Diff orchestration and change collection |
| `checker_policy.py` | Change classification, built-in policies, verdict logic |
| `detectors.py` | ABI change detection rules |
| `reporter.py` | Output formatting (markdown, JSON, SARIF, HTML) |
| `suppression.py` | Suppression rules and symbol filtering |
| `policy_file.py` | Custom YAML policy file parsing |

See [Architecture reference](https://napetrov.github.io/abicheck/reference/architecture/) for the full design documentation.

---

## Documentation

Full documentation is available at **[napetrov.github.io/abicheck](https://napetrov.github.io/abicheck/)**.

**Getting started:**
- [Installation & first check](https://napetrov.github.io/abicheck/getting_started/)
- [Exit codes reference](https://napetrov.github.io/abicheck/exit_codes/)

**Concepts:**
- [Verdicts explained](https://napetrov.github.io/abicheck/concepts/verdicts/) — NO_CHANGE / COMPATIBLE / COMPATIBLE_WITH_RISK / API_BREAK / BREAKING
- [Limitations](https://napetrov.github.io/abicheck/concepts/limitations/)
- [Troubleshooting](https://napetrov.github.io/abicheck/concepts/troubleshooting/)

**User guide:**
- [Policy profiles](https://napetrov.github.io/abicheck/policies/)
- [SARIF output](https://napetrov.github.io/abicheck/sarif_output/)
- [Examples & breakage guide](https://napetrov.github.io/abicheck/examples_breakage_guide/)
- [ABICC migration](https://napetrov.github.io/abicheck/migration/from_abicc/)

**Reference:**
- [Architecture](https://napetrov.github.io/abicheck/reference/architecture/)
- [Change kind reference](https://napetrov.github.io/abicheck/reference/change_kinds/)
- [Benchmark & tool comparison](https://napetrov.github.io/abicheck/tool_comparison/)
- [ABICC compatibility reference](https://napetrov.github.io/abicheck/abicc_compat/)

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions, testing, code style, and PR workflow.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

Copyright 2026 Nikolay Petrov
