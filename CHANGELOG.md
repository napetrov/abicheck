# Changelog

All notable changes to abicheck are documented in this file.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

### Planned
- `--policy-file` schema validation improvements
- Version-stamped typedef suppression (libpng `png_libpng_version_X_Y_Z` pattern)
- Evidence/confidence tiers in JSON output (ELF_ONLY / DWARF_AWARE / HEADER_AWARE)
- Expanded parity test suite coverage

---

## [0.2.0] — 2026-03-18

### Added

#### Cross-Platform Support
- **Windows (PE/COFF)** and **macOS (Mach-O)** binary metadata analysis (exports, imports,
  dependencies) alongside existing Linux (ELF) support.
- **PDB parser**: Windows PE debug info extraction for type-level analysis.
- Windows MSVC/MinGW toolchain support matrix and smoke tests.

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
- All filtering features work across Markdown, JSON, SARIF, and HTML output formats.
  ABICC-compatible XML includes redundancy annotations but does not support `--show-only`.
- Redundancy annotations in SARIF (`caused_by_type`/`caused_count` in result properties,
  `redundant_count` in run properties) and XML (`<redundant_changes>`, `<caused_by>`,
  `<caused_count>` elements in both binary and source sections).

#### Package Extraction Layer (#161)
- Extract and compare shared libraries directly from **RPM, Deb, tar, conda, and wheel**
  packages without manual unpacking.
- Full-stack ABI checking with dependency resolution across package contents.

#### DWARF-only Snapshot Builder ([ADR-003](docs/development/adr/003-data-source-architecture.md))
- Headerless ELF analysis: build ABI snapshots from DWARF debug info alone, without
  requiring public headers or castxml.

#### Full-Stack Dependency Validation (#153)
- `abicheck deps` — show dependency tree and symbol binding status for a binary.
- `abicheck stack-check` — compare a binary's full dependency stack across two sysroots.
- `--follow-deps` flag for `compare` to include dependency info.
- Symbol origin tracking (`SYMBOL_LEAKED_FROM_DEPENDENCY_CHANGED`).

#### Suppression Enhancements (#146)
- `label` field for human-readable suppression rule names.
- `source_location` field for file-scoped suppression rules.
- `expires` field for time-limited suppression rules with automatic expiry.

#### Additional Improvements
- **GitHub Action** (`napetrov/abicheck@v1`) for CI integration.
- **MCP server** for AI agent integration.
- 13 new ABI compatibility test cases (cases 42, 49–62).
- Sentinel enum detection by name pattern (`*_last`/`*_max`/`*_count`).
- `--allow-symbols-only` flag for ELF compare without headers.
- Cross-platform CMake build support for example cases.

### Fixed
- `enum_last_member_value_changed` downgraded to risk severity in policy.
- ABICC compat: auto-forward `abicheck compat <flags>` to `compat check`.
- Test parity fixes for ABICC 2.3.

### Platform
- **Linux** (ELF/DWARF) — full support.
- **Windows** (PE/COFF/PDB) — binary metadata and header AST analysis.
- **macOS** (Mach-O/DWARF) — binary metadata and header AST analysis.

### Installation
- Published to **PyPI**: `pip install abicheck`
- Published to **conda-forge**: `conda install -c conda-forge abicheck`

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

### Platform
- **Linux only** (ELF/DWARF). Windows (PE) and macOS (Mach-O) are not yet supported.

### Installation
- **From source**: `pip install abicheck` or `pip install -e ".[dev]"` for development.
- `castxml` must be installed separately via system packages (`apt install castxml`)
  or conda-forge (`conda install -c conda-forge castxml`)

### Requirements
- Python ≥ 3.10
- `castxml` (mandatory — for header-based C/C++ AST parsing; included in conda-forge install)
- `g++` or `clang++` (accessible to castxml)
- See [Installation](docs/getting-started.md) for full setup instructions

### Known Limitations

- **Suppression system**: label/tag-based suppression, file-scoped suppression (by `source_location`),
  and suppression expiry dates are not yet implemented. Resolved in v0.2.0.

---

[0.1.0]: https://github.com/napetrov/abicheck/releases/tag/v0.1.0
[0.2.0]: https://github.com/napetrov/abicheck/releases/tag/v0.2.0
[Unreleased]: https://github.com/napetrov/abicheck/compare/v0.2.0...HEAD
