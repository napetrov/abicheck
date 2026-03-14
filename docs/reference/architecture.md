# Architecture

## Overview

abicheck is a Python CLI tool that compares two versions of a C/C++ shared library
to detect ABI and API incompatibilities. It uses a 3-layer analysis pipeline to
achieve higher accuracy than tools that rely on a single data source.

**Platform scope:** Linux only — ELF binaries (`.so`), DWARF debug info, and C/C++ headers.
Windows PE and macOS Mach-O are not supported.

---

## Analysis pipeline

```text
                    ┌──────────────────────────────┐
 .so (v1) + headers │  1. ELF: symbols, SONAME,    │
 ──────────────────►│     visibility, binding       │
                    │  2. castxml: Clang AST —      │──► Snapshot (JSON)
                    │     types, vtable, noexcept   │         │
                    │  3. DWARF: size cross-check,  │         │
                    │     offsets, alignment         │         ▼
                    └──────────────────────────────┘    Checker engine
                                                           │
 .so (v2) + headers ──► (same pipeline) ──► Snapshot ──────┘
                                                           │
                                                      Classified changes
                                                      + Verdict
```

### Layer 1: ELF metadata (pyelftools)

Reads the ELF dynamic symbol table (`.dynsym`):

- Exported symbols (functions, variables)
- SONAME
- Symbol binding (GLOBAL, WEAK, LOCAL)
- Symbol versioning (version definitions, requirements)
- NEEDED dependencies
- Visibility attributes

### Layer 2: Header AST (castxml / Clang)

Parses C/C++ headers through castxml to extract:

- Function signatures (parameters, return types)
- Class/struct definitions and layout
- Virtual method tables (vtable slot ordering)
- Enum values and member names
- Typedefs and template instantiations
- `noexcept` specifications
- Access levels (public, protected, private)

This is the primary source for type-level analysis. It catches changes invisible to
DWARF-only tools: `noexcept`, `static` qualifier, const qualifier, access level changes.

### Layer 3: DWARF cross-check (optional)

When DWARF debug info is available in the `.so` files:

- Cross-validates struct/class sizes against header-computed sizes
- Verifies member offsets (catches `#pragma pack` or `-march`-specific alignment differences)
- Checks vtable slot offsets
- Detects calling convention and frame register changes

---

## Key modules

| Module | Responsibility |
|--------|---------------|
| `cli.py` | CLI entrypoint — `dump`, `compare`, `compat check`, `compat dump` commands |
| `dumper.py` | Snapshot generation: reads `.so` + headers → JSON snapshot |
| `checker.py` | Diff orchestration: compares two snapshots, collects changes |
| `checker_policy.py` | `ChangeKind` enum, built-in policy profiles, verdict computation |
| `detectors.py` | Individual ABI change detection rules |
| `policy_file.py` | Custom YAML policy file parsing (`--policy-file`) |
| `reporter.py` | Markdown and JSON output formatting |
| `html_report.py` | HTML report generation |
| `sarif.py` | SARIF output for GitHub Code Scanning |
| `suppression.py` | Suppression rules, symbol/type filtering |
| `serialization.py` | JSON snapshot serialization/deserialization |
| `elf_metadata.py` | ELF reader (layer 1) |
| `dwarf_unified.py` | Unified DWARF handling (layer 3) |
| `dwarf_advanced.py` | Advanced DWARF analysis |
| `dwarf_metadata.py` | DWARF metadata extraction |
| `model.py` | Data models for snapshots and changes |
| `errors.py` | Custom exception definitions |
| `compat/` | ABICC compatibility layer (compat check, compat dump, XML parsing) |

---

## Policy model

Policies control how detected changes are classified (BREAKING, API_BREAK, COMPATIBLE).

**Built-in profiles:**

| Profile | Behavior |
|---------|----------|
| `strict_abi` (default) | Every ABI change at maximum severity |
| `sdk_vendor` | Source-only changes downgraded to COMPATIBLE |
| `plugin_abi` | Calling-convention changes downgraded to COMPATIBLE |

**Custom policies:** YAML files with per-kind `break|warn|ignore` overrides.

Source of truth: `policy_kind_sets()` in `checker_policy.py`.

---

## Verdict system

| Verdict | Exit code | Meaning |
|---------|-----------|---------|
| `NO_CHANGE` | 0 | Identical snapshots |
| `COMPATIBLE` | 0 | Safe changes (new symbols, weak binding) |
| `API_BREAK` | 2 | Source-level break, binary-safe (rename, access change) |
| `BREAKING` | 4 | Binary ABI break — old binaries will fail |

---

## Error model

Public exceptions are defined in `abicheck/errors.py`. Tool errors produce exit code `1`.
