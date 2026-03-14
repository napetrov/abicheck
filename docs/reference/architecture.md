# Architecture

## Overview

abicheck is a Python CLI tool that compares two versions of a C/C++ shared library
to detect ABI and API incompatibilities. On Linux it uses a 3-layer analysis pipeline
to achieve higher accuracy than tools that rely on a single data source. On Windows
and macOS it provides binary metadata analysis (exports, imports, dependencies).

**Supported platforms and binary formats:**

| Platform | Format | Deep analysis (AST + DWARF) | Binary metadata |
|----------|--------|:---------------------------:|:---------------:|
| Linux | ELF (`.so`) | Yes | Yes |
| Windows | PE/COFF (`.dll`) | — | Yes |
| macOS | Mach-O (`.dylib`) | — | Yes |

---

## Analysis pipeline

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
              │ Header AST (castxml) — Linux only  │
              │ DWARF cross-check  — Linux only    │
              └────────────────┬──────────────────┘
                               │
              ┌────────────────▼──────────────────┐
              │    Checker → Changes → Verdict     │
              └───────────────────────────────────┘
```

### Layer 1: Binary metadata

Reads native binary metadata using format-specific parsers:

**ELF** (Linux, via `pyelftools`):
- Exported symbols (functions, variables) from `.dynsym`
- SONAME, symbol binding (GLOBAL, WEAK, LOCAL), symbol versioning
- NEEDED dependencies, visibility attributes

**PE/COFF** (Windows, via `pefile`):
- Exported functions and ordinals from the export table
- Imported DLLs and functions from the import table
- Machine type, characteristics, DLL characteristics
- File and product version from VS_FIXEDFILEINFO resource

**Mach-O** (macOS, via `macholib`):
- Exported symbols from the symbol table (including weak definitions)
- Install name (LC_ID_DYLIB — equivalent of ELF SONAME)
- Dependent libraries (LC_LOAD_DYLIB — equivalent of ELF DT_NEEDED)
- Re-exported libraries (LC_REEXPORT_DYLIB)
- Current and compatibility versions, minimum OS version
- Fat/universal binary support (automatic architecture selection)

### Layer 2: Header AST (castxml / Clang) — Linux only

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

### Layer 3: DWARF cross-check (optional, Linux only)

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
| `dumper.py` | Snapshot generation: reads binary + headers → JSON snapshot |
| `elf_metadata.py` | ELF reader — Linux `.so` binaries (via `pyelftools`) |
| `pe_metadata.py` | PE/COFF reader — Windows `.dll` binaries (via `pefile`) |
| `macho_metadata.py` | Mach-O reader — macOS `.dylib` binaries (via `macholib`) |
| `checker.py` | Diff orchestration: compares two snapshots, collects changes |
| `checker_policy.py` | `ChangeKind` enum, built-in policy profiles, verdict computation |
| `detectors.py` | Individual ABI change detection rules |
| `policy_file.py` | Custom YAML policy file parsing (`--policy-file`) |
| `reporter.py` | Markdown and JSON output formatting |
| `html_report.py` | HTML report generation |
| `sarif.py` | SARIF output for GitHub Code Scanning |
| `suppression.py` | Suppression rules, symbol/type filtering |
| `serialization.py` | JSON snapshot serialization/deserialization |
| `dwarf_unified.py` | Unified DWARF handling (layer 3, Linux only) |
| `dwarf_advanced.py` | Advanced DWARF analysis (Linux only) |
| `dwarf_metadata.py` | DWARF metadata extraction (Linux only) |
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
