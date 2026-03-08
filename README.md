# abicheck

**abicheck checks C/C++ library compatibility at both API and ABI levels.**

abicheck is inspired by two foundational projects:

- [libabigail / abidiff](https://sourceware.org/libabigail/)
- [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/)

Many thanks and kudos to both communities for defining the practical ABI-checking ecosystem.
Sadly, both projects are effectively no longer maintained for many modern contributor workflows,
and it is often not practical to land new fixes there. abicheck is designed to be a
**drop-in replacement for ABICC** while providing a modern, maintainable Python codebase.

---

## Requirements

### Mandatory

- Python 3.10+
- `castxml` (for header-based C/C++ API parsing)
- A C/C++ compiler available to castxml (`g++` or `clang++`)

### Runtime Python dependencies

- `click` (CLI)
- `pyelftools` (ELF/DWARF metadata extraction)
- `defusedxml` (safe ABICC XML parsing)

---

## How to use abicheck

### 1) Create ABI snapshots

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o libfoo-2.0.json
```

### 2) Compare snapshots

```bash
# Markdown report (default)
abicheck compare libfoo-1.0.json libfoo-2.0.json

# JSON
abicheck compare libfoo-1.0.json libfoo-2.0.json --format json -o report.json

# SARIF
abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o report.sarif
```

### 3) ABICC-compatible mode

```bash
abicheck compat -lib foo -old old.xml -new new.xml
```

This mode supports ABICC-style descriptor workflows so teams can migrate without
rewriting their entire pipeline on day one.

---

## abicheck as a drop-in replacement for ABICC

abicheck keeps the ABICC descriptor-driven model available (`compat` mode), while adding:

- Native JSON/SARIF/Markdown outputs for automation
- Easier CI embedding in Python-based tooling
- More explicit architecture with reusable Python modules
- Cleaner evolution path for new ABI rules and checks

Practical migration path:

1. Keep your existing XML descriptor generation.
2. Replace ABICC CLI call with `abicheck compat`.
3. Move to `dump` + `compare` when you want explicit snapshot control and richer outputs.

---

## ABI/API breakages and tool coverage

Below is a high-level matrix aligned with `examples/case01..case24`.

Legend: ✅ supported, ⚠️ partial/context-dependent, ❌ typically unsupported.

| Case | Breakage type | abicheck | abidiff + headers | ABICC #2 (headers) | ABICC #1 (abi-dumper) |
|---|---|:---:|:---:|:---:|:---:|
| case01 | Symbol removed | ✅ | ✅ | ✅ | ✅ |
| case02 | Param type changed | ✅ | ✅ | ✅ | ✅ |
| case03 | Compatible symbol addition | ✅ | ✅ | ✅ | ✅ |
| case04 | No change baseline | ✅ | ✅ | ✅ | ✅ |
| case05 | SONAME policy break | ✅ | ⚠️ | ⚠️ | ⚠️ |
| case06 | Visibility policy break | ✅ | ✅ | ⚠️ | ⚠️ |
| case07 | Struct layout break | ✅ | ✅ | ✅ | ✅ |
| case08 | Enum value changed | ✅ | ⚠️ | ✅ | ✅ |
| case09 | C++ vtable drift | ✅ | ✅ | ✅ | ✅ |
| case10 | Return type changed | ✅ | ✅ | ✅ | ✅ |
| case11 | Global variable type changed | ✅ | ✅ | ✅ | ✅ |
| case12 | Function removed | ✅ | ✅ | ✅ | ✅ |
| case13 | Symbol version policy break | ✅ | ⚠️ | ⚠️ | ⚠️ |
| case14 | Class size/layout change | ✅ | ✅ | ✅ | ✅ |
| case15 | `noexcept` changed | ✅ | ⚠️ | ✅ | ❌ |
| case16 | inline↔non-inline ABI/ODR risk | ✅ | ⚠️ | ✅ | ❌ |
| case17 | Template ABI drift | ✅ | ⚠️ | ✅ | ✅ |
| case18 | Dependency leak via headers | ✅ | ⚠️ | ✅ | ✅ |
| case19 | Enum member removed | ✅ | ✅ | ✅ | ✅ |
| case20 | Enum member value changed | ✅ | ⚠️ | ✅ | ✅ |
| case21 | Method became static | ✅ | ✅ | ✅ | ✅ |
| case22 | Method const qualifier changed | ✅ | ✅ | ✅ | ✅ |
| case23 | Pure virtual method added | ✅ | ✅ | ✅ | ✅ |
| case24 | Union field removed | ✅ | ✅ | ✅ | ✅ |

### Tooling summary

- `abidiff + headers`: strong at ABI diffs when debug/header context is good.
- `ABICC #2` (headers): useful semantic/header-driven mode, with GCC-oriented legacy behavior.
- `ABICC #1` (abi-dumper): strong DWARF pipeline, but depends on debug builds.
- **abicheck**: combines practical header + ELF checks, ABICC compatibility mode,
  and CI-native outputs for production pipelines.

---

## Architecture and dependencies

```text
CLI (abicheck dump | compare | compat)
  -> Dumper (castxml + ELF metadata)
  -> Checker (ABI diff + classification)
  -> Reporters (markdown/json/sarif/html)
```

Key modules:

- `abicheck.cli` — command entry points
- `abicheck.dumper` — builds ABI snapshots
- `abicheck.checker` — computes change sets and verdicts
- `abicheck.compat` — ABICC XML compatibility layer
- `abicheck.reporter`, `abicheck.sarif`, `abicheck.html_report` — output generators
- `abicheck.elf_metadata`, `abicheck.dwarf_metadata`, `abicheck.dwarf_advanced` — metadata extraction

---

## Installation

```bash
pip install -e .
```

---

## Documentation

- [Docs home](docs/index.md)
- [Getting started](docs/getting_started.md)
- [Using abicheck, compatibility modes, and coverage](docs/usage_and_coverage.md)
- [Examples breakage guide](docs/examples_breakage_guide.md)


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

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
