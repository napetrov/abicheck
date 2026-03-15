# Architecture

## Overview

abicheck is a Python CLI tool that compares two versions of a C/C++ shared library
to detect ABI and API incompatibilities. It uses a 3-layer analysis pipeline
to achieve higher accuracy than tools that rely on a single data source.

**Supported platforms and binary formats:**

| Platform | Binary format | Binary metadata | Header AST (castxml) | Debug info cross-check |
|----------|--------------|:---------------:|:--------------------:|:----------------------:|
| Linux | ELF (`.so`) | Yes (pyelftools) | Yes (GCC, Clang) | Yes (DWARF) |
| Windows | PE/COFF (`.dll`) | Yes (pefile) | Yes (MSVC, MinGW) | Planned (PDB) |
| macOS | Mach-O (`.dylib`) | Yes (macholib) | Yes (Clang, GCC) | Yes (DWARF) |

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

### Layer 2: Header AST (castxml / Clang) — all platforms

Parses C/C++ headers through castxml to extract:

- Function signatures (parameters, return types)
- Class/struct definitions and layout
- Virtual method tables (vtable slot ordering)
- Enum values and member names
- Typedefs and template instantiations
- `noexcept` specifications
- Access levels (public, protected, private)

castxml is a cross-platform tool maintained by Kitware (available via conda-forge,
system packages, or direct download for Linux, Windows, and macOS). It is the primary
source for type-level analysis, catching changes invisible to debug-info-only tools:
`noexcept`, `static` qualifier, const qualifier, access level changes.

**Compiler support:** castxml uses an **internal Clang compiler** for parsing but
**emulates** the preprocessor defines, include paths, and target platform of an external
compiler via `--castxml-cc-<id> <compiler-binary>`. At invocation castxml calls the
external compiler to discover its built-in defines (e.g. `__GNUC__`, `__GNUC_MINOR__`,
`_MSC_VER`) and default include search paths, then injects those into its internal Clang
so the resulting AST matches what the external compiler would produce.

| Compiler ID | Compiler | Typical platforms |
|-------------|----------|-------------------|
| `gnu` | GCC / g++ | Linux, macOS, Windows (MinGW) |
| `gnu-c` | GCC / gcc (C mode) | Linux, macOS, Windows (MinGW) |
| `msvc` | Microsoft Visual C++ (cl) | Windows |
| `msvc-c` | Microsoft Visual C (cl, C mode) | Windows |

**Auto-detection logic** (see `dumper.py:_castxml_dump()`): abicheck extracts the
*filename* from the compiler binary path (via `Path(cc_bin).name`) and checks whether it
is exactly `cl` or `cl.exe`. If so, it passes `--castxml-cc-msvc`; otherwise it passes
`--castxml-cc-gnu`. This covers gcc, g++, clang, clang++, and MinGW cross-compilers.

**Compiler resolution priority** (highest to lowest):

1. `--gcc-path /path/to/compiler` — explicit path override, used as-is
2. `--gcc-prefix <prefix>` — cross-toolchain prefix; abicheck appends `g++` (C++ mode)
   or `gcc` (C mode) automatically
3. Default mapping — logical name (`c++` → `g++`, `cc` → `gcc`, `clang++` → `clang++`)

**Scanning with a specific compiler version:** use `--gcc-path` to point at the exact
binary. castxml queries that binary for its version-specific predefined macros and include
paths, so the parse reflects exactly what that compiler version defines:

```bash
abicheck dump libfoo.so -H foo.h --gcc-path /usr/bin/g++-9   # GCC 9
abicheck dump libfoo.so -H foo.h --gcc-path /usr/bin/g++-12  # GCC 12
```

**Limitations — non-C/C++ languages and compiler extensions:**

castxml can only parse **C and C++** because its internal engine is Clang. It cannot parse
Fortran, Rust, Ada, or other languages — there is no `--castxml-cc-fortran` equivalent.
For compilers that add language extensions beyond standard C/C++ (e.g. Intel DPC++/SYCL
`__attribute__((sycl_kernel))`, CUDA `__global__`, OpenACC pragmas), castxml can query
the external compiler's preprocessor state but its internal Clang will reject
extension-specific syntax during parsing. To scan such headers you would need either a
CastXML build linked against the matching Clang fork (e.g. Intel's DPC++ Clang for SYCL)
or a different AST extraction tool that uses that compiler's libclang directly.

### Layer 3: Debug info cross-check (optional)

When debug info is available in the binary:

**DWARF** (Linux `.so`, macOS `.dylib` — via `pyelftools`):
- Cross-validates struct/class sizes against header-computed sizes
- Verifies member offsets (catches `#pragma pack` or `-march`-specific alignment differences)
- Checks vtable slot offsets
- Detects calling convention and frame register changes

**PDB** (Windows `.dll` — planned):
- Windows uses PDB (Program Database) files for debug information
- PDB cross-check support is planned for a future release

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
