# Sprint 9 — ABICC-compatible HTML output

## Overview

Sprint 9 adds a fully self-contained HTML report format to `abicheck` that mirrors
the structure of [abi-compliance-checker (ABICC)](https://github.com/lvc/abi-compliance-checker) reports.

## Usage

### `compare` command

```bash
# Generate HTML report from two snapshots
abicheck compare old.json new.json --format html -o report.html

# Other formats still available
abicheck compare old.json new.json --format markdown
abicheck compare old.json new.json --format sarif -o results.sarif
```

### `compat` command (ABICC drop-in)

```bash
# HTML is the default output format
abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path report.html
```

## Report Layout

The generated HTML report contains:

| Section | Description |
|---------|-------------|
| **Verdict banner** | BREAKING / COMPATIBLE / NO_CHANGE with colour coding |
| **Binary Compatibility %** | Computed as `(old_symbols - breaking) / old_symbols × 100` |
| **Navigation bar** | Anchor links to each change section |
| **Change Summary** | Table of Removed / Changed / Added counts by category |
| **Removed Symbols** | Symbols no longer present in the new version |
| **Changed Symbols** | Symbols present in both versions but with ABI-incompatible changes |
| **Added Symbols** | New symbols (compatible additions) |
| **Suppressed Changes** | Changes filtered by a suppression file (audit trail) |

## Binary Compatibility %

- Computed from the total number of ABI-visible exported symbols in the **old** library
  (functions + variables with `PUBLIC` or `ELF_ONLY` visibility).
- If the old symbol count is 0 or unavailable, falls back to a change-ratio approximation.
- Clamped to `0%` if breaking changes exceed the symbol count (e.g. stale snapshot).

## Change Categories

Changes are grouped into:

- **Functions** — `func_*` kinds
- **Variables** — `var_*` kinds
- **Types** — `type_*`, `struct_*`, `union_*`, `field_*`, `typedef_*` kinds
- **Enums** — `enum_*` kinds
- **ELF / DWARF** — `soname_*`, `symbol_*`, `needed_*`, `rpath_*`, `dwarf_*` kinds

## Symbol Display

C++ symbol names are displayed as **demangled** text with the raw mangled name
available in a tooltip (`<abbr title="mangled">demangled</abbr>`).
