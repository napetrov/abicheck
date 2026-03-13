# Changelog

All notable changes to abicheck are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)  
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [0.1.0] — 2026-03-13

First public release of abicheck — a modern, Python-native ABI compatibility checker
for C/C++ shared libraries, designed as a drop-in replacement for
[abi-compliance-checker (ABICC)](https://lvc.github.io/abi-compliance-checker/) with
additional capabilities.

### Features

#### Core Analysis
- **Multi-tier detection**: castxml (header AST) + ELF symbol table + DWARF debug info
- **85 ChangeKinds** across BREAKING / API_BREAK / COMPATIBLE severity tiers
- **100% ABICC parity** for 55 documented ABI break scenarios; exceeds ABICC in 6 additional scenarios
- Works on **release builds** with headers + `.so` — no debug symbols required for core checks

#### ABI Break Detection
- Function/variable add/remove/type changes
- Struct/class size, alignment, field offset, vtable changes
- Enum member add/remove/rename/value changes
- Return type, parameter type/count/default changes
- noexcept, virtual, pure-virtual, static, const, volatile method changes
- Base class add/remove/reorder (multiple inheritance)
- Symbol binding/type/visibility changes
- ELF metadata: SONAME, DT_NEEDED, DT_RPATH, IFUNC, symbol versioning, TLS
- DWARF advanced: calling convention, frame register (CFA) drift, value ABI trait
  - CFA extraction uses modal heuristic (not max-PC) to avoid epilogue bias
  - `.dynsym` takes priority over `.symtab` (local symbols never shadow exported names)

#### Policy System
- **Built-in profiles**: `strict_abi` (default), `sdk_vendor`, `plugin_abi`
- **`--policy-file`**: YAML-based per-kind verdict overrides for project-specific rules
- `DiffResult.policy` field — all classification buckets (`breaking`, `source_breaks`, `compatible`) are policy-aware
- Single source of truth: `policy_kind_sets()` in `checker_policy.py`

#### CLI
- `abicheck dump` — create ABI snapshot JSON from `.so` + headers
- `abicheck compare` — diff two snapshots with `--policy`, `--policy-file`, `--format` (markdown/json/sarif/html), `--suppress`
- `abicheck compat check` — ABICC drop-in CLI (accepts all ABICC flags)
- `abicheck compat dump` — create snapshot from ABICC XML descriptor
- `abicheck --version` — print version

#### Reports
- Markdown, JSON, SARIF, HTML report formats
- Split reports: `--bin-report-path` / `--src-report-path` (binary vs source breaks)
- Suppression system: YAML rules with symbol/type/version/platform/scope filters
- RE2-based suppression engine (O(N) guaranteed, no ReDoS)

#### ABICC Compatibility
- Drop-in: all major ABICC flags accepted (`-strict`, `-source`, `-binary`, `-warn-newsym`, etc.)
- ABICC XML descriptor support via `abicheck compat`
- ABICC-compatible HTML report output (`-old-style`)
- Exit codes mirror ABICC (0/1/2)

### Platform
- **Linux only** (ELF/DWARF). Windows (PE) and macOS (Mach-O) are not yet supported.

### Installation
- **From source** (only option for now — not yet published to PyPI or conda-forge):
  `git clone … && pip install -e ".[dev]"`
- `castxml` must be installed separately via system packages (`apt install castxml`)
  or conda-forge (`conda install -c conda-forge castxml`)

### Requirements
- Python ≥ 3.10
- `castxml` (mandatory — for header-based C/C++ AST parsing; included in conda-forge install)
- `g++` or `clang++` (accessible to castxml)
- See [Installation](docs/getting_started.md) for full setup instructions

### Known Limitations

- **Suppression system**: label/tag-based suppression, file-scoped suppression (by `source_location`),
  and suppression expiry dates are not yet implemented. Planned for v0.2.

---

## [Unreleased]

### Added
- `--lang` option on `dump` and `compare` — select C (`--lang c`) or C++ (`--lang c++`, default) mode for castxml
- Cross-compilation flags on native `dump` command: `--gcc-path`, `--gcc-prefix`, `--gcc-options`, `--sysroot`, `--nostdinc`
- `--verbose` / `-v` flag on `dump` and `compare` for debug logging
- `compat` is now a command group: `abicheck compat check` (was `abicheck compat`), `abicheck compat dump` (was `abicheck compat-dump`)
- Exit codes documented in `compare --help` output

### Changed
- `--compiler` option renamed to `--lang` (breaking CLI change)
- Dump error handling uses `click.ClickException` (exit 1) instead of `sys.exit(2)`
- Snapshot reconstruction uses `dataclasses.replace()` for safety
- `-o` alias removed from `-old` in `compat check` to avoid collision with `-o/--output`

### Planned
- Windows PE support
- Expanded parity test suite
- `--policy-file` schema validation improvements

[0.1.0]: https://github.com/napetrov/abicheck/releases/tag/v0.1.0
[Unreleased]: https://github.com/napetrov/abicheck/compare/v0.1.0...HEAD
