# Using abicheck, Compatibility Modes, and Coverage

## What abicheck is

**abicheck** checks C/C++ library compatibility on both API and ABI layers.
It is designed to be a practical, modern replacement for legacy ABI tooling in CI,
especially when you need structured output and automation.

abicheck is inspired by:

- [libabigail / abidiff](https://sourceware.org/libabigail/)
- [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/)

Huge thanks to both projects for pioneering ABI compatibility analysis.

## How to use abicheck

The standard flow has 2 steps:

1. **Dump** ABI snapshots from each library version.
2. **Compare** snapshots and act on verdict (`NO_CHANGE`, `COMPATIBLE`, `BREAKING`).

### 1) Dump snapshots

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o libfoo-2.0.json
```

### 2) Compare snapshots

```bash
# Human-readable markdown in terminal
abicheck compare libfoo-1.0.json libfoo-2.0.json

# JSON report
abicheck compare libfoo-1.0.json libfoo-2.0.json --format json -o abi-report.json

# SARIF for GitHub code scanning
abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o abi-report.sarif
```

### ABICC-compatible invocation

abicheck supports ABICC-style descriptor input as a drop-in workflow.
See [ABICC compatibility reference](abicc_compat.md) for the full flag list.

```bash
# Minimal (identical to abi-compliance-checker):
abicheck compat -lib foo -old old.xml -new new.xml

# With strict mode and version labels:
abicheck compat -lib foo -old old.xml -new new.xml -s -v1 1.0 -v2 2.0

# Source/API compat only (ignore ELF metadata):
abicheck compat -lib foo -old old.xml -new new.xml -source

# Skip known symbols:
abicheck compat -lib foo -old old.xml -new new.xml -skip-symbols skip.txt
```

## abicheck as a drop-in replacement for ABICC

abicheck intentionally supports ABICC-like CLI semantics and XML descriptor flow,
while modernizing internals and outputs.

### Why teams replace ABICC with abicheck

- Python-native implementation, easier to embed and extend in CI.
- Structured outputs (`json`, `markdown`, `sarif`) for machine + human consumption.
- Works well in stripped-binary workflows when combined with headers.
- Better integration path for modern C++ workflows and policy checks.
- **Full ABICC flag parity** — `-s/-strict`, `-source`, `-skip-symbols/-skip-types`, `-v1/-v2`, `-stdout` and more.
- **Superset detectors** — catches everything ABICC catches plus: `FUNC_DELETED`, `VAR_BECAME_CONST`, `TYPE_BECAME_OPAQUE`, `BASE_CLASS_POSITION_CHANGED`, `BASE_CLASS_VIRTUAL_CHANGED`.

### Practical migration path

1. Keep your existing ABICC XML descriptor generation.
2. Replace ABICC compare call with `abicheck compat ...` (flags are identical).
3. Optionally move to native `dump/compare` commands for explicit snapshot control.
4. Switch CI gates to JSON/SARIF-based policy checks.

## Change classification: BREAKING vs COMPATIBLE

abicheck classifies every detected change into a verdict:

- **BREAKING** — binary ABI incompatibility; existing binaries will malfunction.
- **COMPATIBLE** — informational/warning; does not break binary compatibility on its own.
- **NO_CHANGE** — identical ABI.

A change is BREAKING only when it causes binary-level failures: symbol resolution errors,
type layout corruption, vtable mismatch, or calling convention incompatibility.

Changes like `noexcept` addition/removal, enum member addition, union field addition,
GLOBAL→WEAK binding, and IFUNC transitions are classified as **COMPATIBLE** — they are
detected and reported for awareness but do not trigger a BREAKING verdict. See the
[ABI Break Catalog](abi_breaking_cases_catalog.md) for the full
rationale table.

## ABI/API breakages and tool coverage

High-level guidance:

- `abicheck compare` is the canonical mode for highest-fidelity verdicts (`NO_CHANGE`, `COMPATIBLE`, `API_BREAK`, `BREAKING`).
- `abicheck compat` is the ABICC drop-in mode and intentionally constrained to ABICC-style semantics.
- `abicheck compat -s` (`strict`) intentionally promotes compatible changes to breaking for conservative policy gates.

To avoid data drift, detailed per-case matrices are maintained in dedicated docs:

- [Benchmark report](benchmark_report.md) — exact scored results, denominators, and timing notes
- [Tool comparison](tool_comparison.md) — interpretation and trade-offs by workflow
- [ABI break catalog](abi_breaking_cases_catalog.md) — rationale for classification of each change kind

This page intentionally keeps only workflow-level guidance and links to those canonical sources.

## Architecture and dependencies

## High-level architecture

```text
CLI (dump/compare/compat)
  -> dumper (castxml AST + ELF metadata)
  -> checker (rule-based diff + severity)
  -> reporters (markdown/json/sarif/html)
```

## Core modules and purpose

- `abicheck.cli` — command-line entrypoints.
- `abicheck.dumper` — snapshot construction from headers + binary metadata.
- `abicheck.checker` — change detection and breakage classification.
- `abicheck.compat` — ABICC XML descriptor compatibility layer.
- `abicheck.reporter` / `abicheck.sarif` / `abicheck.html_report` — output generators.
- `abicheck.elf_metadata`, `abicheck.dwarf_metadata`, `abicheck.dwarf_advanced` — low-level binary metadata extraction.

## Runtime dependencies (practical view)

- **Python 3.10+**
- **castxml** (for header-driven API/ABI modeling)
- **pyelftools** (ELF/DWARF metadata)
- **click** (CLI)
- **defusedxml** (safe XML parsing for ABICC descriptor mode)

Optional ecosystem tools for comparisons/benchmarks:

- `abidiff` / libabigail tools
- ABICC + abi-dumper toolchain

