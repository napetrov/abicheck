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

## ABI/API breakages and what each tool mode can detect

This section maps breakage types to example cases under `examples/` and compares:

- `abicheck` (header + ELF metadata pipeline)
- `abidiff + headers`
- `ABICC Usage #2` (header-based ABICC mode)
- `ABICC Usage #1` (abi-dumper / DWARF dump mode)

Legend: ✅ strong support, ⚠️ partial/conditional, ❌ generally not covered.

| Case | Breakage type | Verdict | abicheck | abidiff + headers | ABICC #2 (headers) | ABICC #1 (dumps) |
|---|---|---|:---:|:---:|:---:|:---:|
| case01_symbol_removal | Public symbol removed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case02_param_type_change | Function parameter type changed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case03_compat_addition | Compatible API addition | COMPATIBLE | ✅ | ✅ | ✅ | ✅ |
| case04_no_change | No ABI change baseline | NO_CHANGE | ✅ | ✅ | ✅ | ✅ |
| case05_soname | SONAME / packaging policy issue | BREAKING | ✅ | ⚠️ | ⚠️ | ⚠️ |
| case06_visibility | Visibility/export policy drift | BREAKING | ✅ | ✅ | ⚠️ | ⚠️ |
| case07_struct_layout | Struct layout changed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case08_enum_value_change | Enum value changed | BREAKING | ✅ | ⚠️ | ✅ | ✅ |
| case09_cpp_vtable | VTable/method order/signature drift | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case10_return_type | Function return type changed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case11_global_var_type | Global variable type changed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case12_function_removed | API function removed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case13_symbol_versioning | Symbol version policy regression | COMPATIBLE | ✅ | ⚠️ | ⚠️ | ⚠️ |
| case14_cpp_class_size | C++ class size/layout changed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case15_noexcept_change | `noexcept` contract changed | COMPATIBLE | ✅ | ⚠️ | ✅ | ❌ |
| case16_inline_to_non_inline | Inline/ODR surface change | BREAKING | ✅ | ⚠️ | ✅ | ❌ |
| case17_template_abi | Template-instantiation ABI drift | BREAKING | ✅ | ⚠️ | ✅ | ✅ |
| case18_dependency_leak | Transitive dependency leaked into API | BREAKING | ✅ | ⚠️ | ✅ | ✅ |
| case19_enum_member_removed | Enum member removed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case20_enum_member_value_changed | Enum member value changed | BREAKING | ✅ | ⚠️ | ✅ | ✅ |
| case21_method_became_static | Method became static | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case22_method_const_changed | Method const-qualifier changed | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case23_pure_virtual_added | Added pure virtual method | BREAKING | ✅ | ✅ | ✅ | ✅ |
| case24_union_field_removed | Union field removed | BREAKING | ✅ | ✅ | ✅ | ✅ |

### Summary by breakage category

- **API surface breaks** (removed/changed signatures): all modes generally catch these.
- **C++ semantic contract breaks** (`noexcept`, inline/ODR): header-aware analysis is strongest.
- **DWARF-only detail** (some anonymous/internal layout details): ABICC dump mode can be strongest when debug info exists.
- **Policy/linking hygiene** (SONAME/versioning/visibility): best handled by a tool that includes explicit ELF policy checks.

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
- `abicheck.compat` — ABICC compatibility layer (`abicheck.compat.descriptor`, `abicheck.compat.xml_report`, `abicheck.compat.cli`, `abicheck.compat.abicc_dump_import`).
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

