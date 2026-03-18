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
- `abicheck compat` — ABICC drop-in CLI (accepts all ABICC flags)
- `abicheck compat-dump` — create snapshot from ABICC XML descriptor
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

#### Deployment Risk Verdict
- New verdict `COMPATIBLE_WITH_RISK`: binary-compatible changes that pose a deployment
  risk requiring manual verification of target environment constraints.
- `RISK_KINDS` classification set in `checker_policy.py` (currently: `SYMBOL_VERSION_REQUIRED_ADDED`).
- `DiffResult.risk` property to query risk-classified changes.
- `"risk"` severity level in YAML policy files (maps to `COMPATIBLE_WITH_RISK`).
- `SYMBOL_VERSION_REQUIRED_ADDED` moved from `BREAKING_KINDS` → `RISK_KINDS`:
  new GLIBC version requirements in `DT_VERNEED` now produce `COMPATIBLE_WITH_RISK`
  instead of `BREAKING` — existing compiled consumers are unaffected (already linked).
- `policy_kind_sets()` now returns a 4-tuple `(breaking, api_break, compatible, risk)`.
- `plugin_abi` policy treats `SYMBOL_VERSION_REQUIRED_ADDED` as `BREAKING`
  (host/plugin deployment-floor raise is an in-process load blocker).
- `_apply_warn_newsym` promotes `COMPATIBLE_WITH_RISK` → `BREAKING` when `-warn-newsym` is active.

#### SARIF exit code changes (migration note)
- `BREAKING`: exit code `1` → `4`
- `API_BREAK`: now emits `2` (was `0`)
- `COMPATIBLE_WITH_RISK`: emits `0` (binary-compatible; risk surfaced via `exitCodeDescription`)
- If your CI pipeline checks `exitCode == 1` on BREAKING, update to `exitCode == 4`.

---

## [Unreleased]

### Added

#### Report Filtering & Deduplication ([ADR-004](docs/development/adr/004-report-filtering-and-deduplication.md))
- **Redundancy filtering**: Automatically collapses derived changes caused by root type changes
  (e.g. a struct size change that propagates to 30 `FUNC_PARAMS_CHANGED` entries). Root type
  changes are annotated with `caused_count` and `affected_symbols`. Use `--show-redundant` to
  disable filtering.
- **`--show-only`**: Comma-separated filter tokens to limit displayed changes by severity
  (`breaking`, `api-break`, `risk`, `compatible`), element (`functions`, `variables`, `types`,
  `enums`, `elf`), or action (`added`, `removed`, `changed`). AND across dimensions, OR within.
  Does not affect verdict or exit codes. Invalid tokens produce a clean CLI error.
- **`--stat`**: One-line summary mode for CI gates. With `--format json`, emits only the summary
  object (no changes array).
- **`--report-mode leaf`**: Root-type-grouped output that lists affected interfaces under each
  root type change, instead of listing every change individually.
- **`--show-impact`**: Appends an impact summary table showing root changes and how many
  interfaces each affects, with separate columns for direct and derived counts.
- All filtering features work across all output formats: Markdown, JSON, SARIF, HTML, and
  ABICC-compatible XML.
- Redundancy annotations in SARIF (`caused_by_type`/`caused_count` in result properties,
  `redundant_count` in run properties) and XML (`<redundant_changes>`, `<caused_by>`,
  `<caused_count>` elements in both binary and source sections).

### Planned
- Windows PE support
- Expanded parity test suite
- `--policy-file` schema validation improvements
- Version-stamped typedef suppression (libpng `png_libpng_version_X_Y_Z` pattern)

[0.1.0]: https://github.com/napetrov/abicheck/releases/tag/v0.1.0
[Unreleased]: https://github.com/napetrov/abicheck/compare/v0.1.0...HEAD
