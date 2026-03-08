# abicheck

**abicheck** is a modern ABI compatibility checker for C/C++ shared libraries.

It is designed as a modular, compiler-agnostic alternative to
[abi-compliance-checker](https://github.com/lvc/abi-compliance-checker),
using Clang as the parsing backend (GCC can optionally configure target settings).

---

## Problem Statement

Existing ABI checking tools have significant limitations in CI/CD pipelines for
modern C++ libraries:

- **abi-compliance-checker**: written in Perl, hard GCC dependency via
  `-fdump-lang-spec`, no Clang/LLVM support, difficult to extend or embed.
- **abidiff** (libabigail): excellent binary-level ELF diff, but requires DWARF
  debug symbols; many release builds strip them.
- **Symbol-only diffing** (`nm`, `objdump`): no type-level information, many
  false positives/negatives.

**The gap:** There is no lightweight, embeddable tool that:
1. Works from headers + release `.so` (no debug symbols required)
2. Uses Clang (via castxml) as the parsing backend; GCC may be specified to match build macros/target
3. Produces structured, machine-readable ABI reports
4. Can be embedded in CI pipelines without Perl or heavy toolchain dependencies

---

## Goals

### Must Have
- Parse C/C++ public API from headers using **castxml** (Clang-based,
  compiler-agnostic)
- Extract exported symbol list from `.so` (ELF, no debug info required)
- Diff two ABI snapshots and classify changes:
  - `BREAKING`: removed/renamed public symbols, incompatible type changes,
    vtable changes, alignment changes
  - `COMPATIBLE`: added symbols, internal changes
  - `NO_CHANGE`: identical ABI
- Structured output: JSON + Markdown report
- CLI: `abicheck dump`, `abicheck compare`

### Should Have
- Clang-based parsing via castxml (GCC can be specified for macro/target compatibility)
- Suppression file support (filter known/intentional ABI changes)
- Per-symbol classification: public / ELF-only / hidden visibility

### Nice to Have
- HTML report
- Version history scanning (compare all releases of a library)
- GitHub Actions integration

---

## Architecture

```
+-------------------------------------------------------------+
|                        CLI                                    |
|          abicheck dump | compare | compat                    |
+----------------+------------------------+--------------------+
                 |                        |
        +--------v--------+     +--------v--------+
        |    DUMPER        |     |    CHECKER      |
        |                  |     |                 |
        | castxml + ELF    |     | diff(a, b)      |
        |   |              |     |   |             |
        | ABI snapshot     |     | classify change |
        | (JSON)           |     |   |             |
        |                  |     | verdict         |
        +--------+---------+    +--------+---------+
                 |                        |
                 +------------+-----------+
                              |
                     +--------v--------+
                     |    REPORTER     |
                     | JSON / MD / HTML|
                     +-----------------+
```

### Components

| Component | Description | Key dependency |
|-----------|-------------|----------------|
| `abicheck.dumper` | Headers + `.so` -> ABI snapshot JSON | `castxml`, `pyelftools` |
| `abicheck.checker` | Diff two snapshots -> classified changes | pure Python |
| `abicheck.reporter` | Changes -> structured report | pure Python |
| `abicheck.html_report` | HTML report generator | pure Python |
| `abicheck.elf_metadata` | ELF dynamic section + symbol metadata | `pyelftools` |
| `abicheck.dwarf_metadata` | DWARF type layout extraction | `pyelftools` |
| `abicheck.dwarf_advanced` | Calling convention, packing, flags | `pyelftools` |
| `abicheck.compat` | ABICC XML descriptor compatibility layer | `defusedxml` |
| `abicheck.cli` | Command-line interface | `click` |

### ABI Snapshot Format (JSON)

```json
{
  "library": "libfoo.so.1",
  "version": "1.2.3",
  "functions": [
    {
      "name": "foo_init",
      "mangled": "_Z8foo_initv",
      "return_type": "int",
      "params": [],
      "visibility": "public",
      "source_location": "foo.h:12"
    }
  ],
  "types": [...],
  "variables": [
    {
      "name": "global_flag",
      "mangled": "_Z11global_flag",
      "type": "int",
      "visibility": "public",
      "source_location": "globals.h:5"
    }
  ]
}
```

---

## Suppression Files

Suppression files let you silence known or intentional ABI changes so they don't
block your CI pipeline. Each rule matches on symbol name (exact or regex) and,
optionally, on change kind.

### Format

```yaml
# abicheck suppression file
version: 1
suppressions:
  - symbol: "_ZN3foo3barEv"          # exact mangled name
    change_kind: "func_removed"       # optional: only suppress this change kind
    reason: "intentional removal in v2"

  - symbol_pattern: "^_ZN.*privateEv$"  # regex (mutually exclusive with symbol)
    reason: "private implementation detail"

  - symbol_pattern: ".*detail.*"
    reason: "internal namespace -- not public API"
```

Fields:

| Field | Required | Description |
|---|---|---|
| `symbol` | one of | Exact mangled symbol name |
| `symbol_pattern` | one of | Python `re.fullmatch` pattern (must match entire symbol name; use `.*` for substring matching) |
| `change_kind` | optional | `ChangeKind` value (e.g. `func_removed`); omit to suppress all kinds |
| `reason` | optional | Human-readable note |

### CLI Usage

```bash
abicheck compare libfoo-1.0.json libfoo-2.0.json --suppress suppressions.yaml
```

When suppressions are active the Markdown report includes a footer:

```text
> i 3 change(s) suppressed via suppression file
```

See `examples/suppression_example.yaml` for realistic examples.

## Why castxml?

[castxml](https://github.com/CastXML/CastXML) converts C/C++ source to an XML
description of the AST using Clang as the parsing backend. It:

- Clang-based parsing; GCC may be specified via `--compiler` to match build macros/target settings
- Is widely used in the C++ ecosystem (SWIG, pygccxml, ROOT/Cling)
- Handles most C++ features including templates, namespaces, inheritance
- Produces a stable, well-documented XML format
- Is actively maintained (Apache-2.0 license)

---

## Prerequisites

- **castxml** -- `apt install castxml` or `conda install -c conda-forge castxml`
  (optional: only needed for header-based type analysis; ELF/DWARF analysis works without it)
- **Python 3.10+**
- **g++** or **clang++** (compiler for castxml to use when parsing headers)

## Installation

```bash
# Install from source (not yet on PyPI):
pip install -e .
```

## Quick Start

```bash
# Dump ABI snapshot
abicheck dump libfoo.so.1 -H include/foo.h --version 1.2.3 -o snap-1.2.3.json

# Compare two versions
abicheck compare snap-1.2.3.json snap-1.3.0.json

# ABICC-compatible mode (reads XML descriptors)
abicheck compat -lib libfoo -old old.xml -new new.xml
```


---

## Testing and coverage

```bash
# fast tests (default CI gate — matches workflow)
pytest tests/ -v --tb=short -m "not integration and not libabigail" \
  --cov=abicheck --cov-report=term-missing --cov-report=xml --cov-fail-under=52

# full local suite (includes integration/parity when deps are present)
pytest --cov=abicheck --cov-report=term-missing
```

Coverage settings are centralized in `pyproject.toml` and CI publishes `coverage.xml` as an artifact.
See `docs/testing_coverage.md` for the current baseline and a gap analysis.

---

## License

**Apache License 2.0** -- see [LICENSE](LICENSE).

> **Note on third-party tools:**
> This project does **not** contain any code derived from
> `abi-compliance-checker` (LGPL-2.1) or `libabigail` (LGPL-3.0+).
> castxml itself is Apache-2.0 licensed.
> See [NOTICE.md](NOTICE.md) for full third-party notices.
