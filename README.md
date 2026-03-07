# abi-check

**abi-check** is a Python-native ABI compatibility checker for C/C++ shared libraries.

It is designed as a modular, LLVM/GCC-agnostic replacement for existing ABI checking tools, with first-class support for Intel oneAPI packages.

---

## Problem Statement

Existing ABI checking tools have significant limitations in CI/CD pipelines for modern C++ libraries:

- **abi-compliance-checker** (ABICC): written in Perl, hard GCC dependency via `-fdump-lang-spec`, limited Clang/LLVM support, difficult to extend or embed.
- **abidiff** (libabigail): excellent binary-level ELF diff, but requires DWARF debug symbols; many release builds strip them.
- **Symbol-only diffing** (`nm`, `objdump`): no type-level information, many false positives/negatives.

**The gap:** There is no lightweight, Python-native tool that:
1. Works from headers + release `.so` (no debug symbols required)
2. Supports both GCC and Clang/LLVM as the parsing frontend
3. Produces structured, machine-readable ABI reports
4. Can be embedded in CI pipelines without Perl/heavy dependencies

---

## Goals

### Must Have
- [ ] Parse C/C++ public API from headers using **castxml** (Clang-based, compiler-agnostic)
- [ ] Extract exported symbol list from `.so` (ELF, no debug info required)
- [ ] Diff two ABI snapshots and classify changes:
  - `BREAKING`: removed/renamed public symbols, incompatible type changes, vtable changes
  - `SOURCE_BREAK`: API-level changes (signature, default args) not visible in binary
  - `COMPATIBLE`: added symbols, internal changes
  - `NO_CHANGE`: identical ABI
- [ ] Structured output: JSON + Markdown report
- [ ] CLI: `abi-check dump`, `abi-check compare`, `abi-check scan` (version history)

### Should Have
- [ ] LLVM/Clang support as first-class frontend (via castxml)
- [ ] GCC support (via castxml)
- [ ] Suppression file support (filter known/intentional ABI changes)
- [ ] Per-symbol classification: public / internal (hidden visibility) / ELF-only

### Nice to Have
- [ ] HTML report
- [ ] Integration with package managers (APT, conda) for automated version scanning
- [ ] GitHub Actions workflow

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                        CLI                              │
│          abi-check dump | compare | scan                │
└──────────────┬────────────────────┬─────────────────────┘
               │                    │
      ┌────────▼────────┐  ┌────────▼────────┐
      │    DUMPER       │  │    CHECKER      │
      │                 │  │                 │
      │ castxml         │  │ diff(a, b)      │
      │   ↓             │  │   ↓             │
      │ ABI snapshot    │  │ classify change │
      │ (JSON)          │  │   ↓             │
      │                 │  │ verdict         │
      └────────┬────────┘  └────────┬────────┘
               │                    │
               └────────┬───────────┘
                        │
               ┌────────▼────────┐
               │    REPORTER     │
               │ JSON / Markdown │
               │ / HTML          │
               └─────────────────┘
```

### Components

| Component | Description | Key dependency |
|-----------|-------------|----------------|
| `abi_check.dumper` | Headers + `.so` → ABI snapshot JSON | `castxml` |
| `abi_check.checker` | Diff two snapshots → classified changes | pure Python |
| `abi_check.reporter` | Changes → structured report | pure Python |
| `abi_check.cli` | Command-line interface | `click` |

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
  "variables": [...],
  "vtables": [...]
}
```

---

## Why castxml?

[castxml](https://github.com/CastXML/CastXML) converts C/C++ source to an XML description of the AST, using Clang as the parsing backend. It:

- Supports **GCC and Clang** (LLVM) as frontends
- Is widely used (SWIG, pygccxml, ROOT/Cling)
- Handles most C++ features including templates, namespaces, inheritance
- Produces a stable, well-documented XML format (GCC-XML)
- Is actively maintained (CastXML project)

Unlike ABICC's Perl-based header parser, castxml is a proper C++ frontend and handles edge cases (SFINAE, concepts, attribute visibility) correctly.

---

## License

**Apache License 2.0** — see [LICENSE](LICENSE).

> **Note on third-party tools:**  
> This project does **not** contain any code derived from `abi-compliance-checker` (LGPL-2.1) or `libabigail` (LGPL-2.1+).  
> castxml itself is Apache-2.0 licensed.  
> See [NOTICE.md](NOTICE.md) for full third-party notices.

---

## Status

🚧 **Early development / POC**

- [ ] Dumper POC (castxml integration)
- [ ] Checker POC (diff + verdict)
- [ ] Test suite (independent fixtures)
- [ ] CLI skeleton
