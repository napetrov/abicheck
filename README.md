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
# Minimal (same flags as abi-compliance-checker):
abicheck compat -lib foo -old old.xml -new new.xml

# Full flag parity:
abicheck compat -lib foo -old old.xml -new new.xml \
  -report-path report.html \
  -s \
  -show-retval \
  -v1 1.0 -v2 2.0
```

This mode supports ABICC-style descriptor workflows so teams can migrate without
rewriting their entire pipeline on day one. See [ABICC compatibility reference](docs/abicc_compat.md) for full flag list.

---

## abicheck as a drop-in replacement for ABICC

abicheck keeps the ABICC descriptor-driven model available (`compat` mode), while adding:

- Native JSON/SARIF/Markdown outputs for automation
- Easier CI embedding in Python-based tooling
- More explicit architecture with reusable Python modules
- Cleaner evolution path for new ABI rules and checks
- **Superset detectors** — finds everything ABICC finds, plus more (see [gap report](docs/gap_report.md))

### Migration: one-line swap

```bash
# Before:
abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

# After (identical):
abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html
```

### Supported ABICC flags

| Flag | Alias(es) | Description |
|------|-----------|-------------|
| `-lib NAME` | `-l`, `-library` | Library name |
| `-old PATH` | `-d1` | Old version descriptor |
| `-new PATH` | `-d2` | New version descriptor |
| `-report-path PATH` | | Output report path |
| `-report-format FMT` | | `html` / `json` / `md` (default: `html`) |
| `-s` | `-strict` | Any change → exit 1 (BREAKING) |
| `-source` | `-src`, `-api` | Source/API compat only (filter ELF-only changes) |
| `-binary` | `-bin`, `-abi` | Binary ABI mode (default) |
| `-show-retval` | | Include return-value changes in report |
| `-v1 NUM` | `-vnum1` | Override old version label |
| `-v2 NUM` | `-vnum2` | Override new version label |
| `-title NAME` | | Custom report title |
| `-skip-symbols PATH` | | File with symbols to suppress |
| `-skip-types PATH` | | File with types to suppress |
| `-stdout` | | Print report to stdout |
| `-headers-only` | | _(reserved — not yet implemented)_ |
| `-skip-headers PATH` | | _(reserved — not yet implemented)_ |

Practical migration path:

1. Keep your existing XML descriptor generation.
2. Replace ABICC CLI call with `abicheck compat`.
3. Move to `dump` + `compare` when you want explicit snapshot control and richer outputs.

---

## Change classification: BREAKING vs COMPATIBLE

abicheck classifies every detected change into one of three verdicts:

| Verdict | Meaning | CI gate recommendation |
|---|---|---|
| **BREAKING** | Binary ABI incompatibility — existing binaries will malfunction | Fail the build |
| **COMPATIBLE** | Informational/warning change that does not break binary compatibility on its own | Warn, do not fail |
| **NO_CHANGE** | Identical ABI | Pass |

### What counts as BREAKING

A change is classified as BREAKING only if it causes **binary-level incompatibility**
when swapping a shared library between two releases without recompiling consumers:

- Symbol removal/disappearance (loader fails with unresolved symbol)
- Type layout changes (size, alignment, field offsets — causes memory corruption)
- Vtable changes (virtual dispatch goes to wrong function)
- Calling convention changes (args in wrong registers)
- Function signature changes (return type, parameters, static qualifier, cv-qualifiers)
- SONAME change (dynamic linker can't find the library)

### What counts as COMPATIBLE (informational/warning)

These changes are detected and reported but do **not** trigger a BREAKING verdict
because they do not cause binary linkage or layout failures on their own:

| Change | Why it's not a binary ABI break |
|---|---|
| `noexcept` added/removed | Itanium ABI mangling unchanged; same symbol resolves. Source-level type concern only. |
| Enum member added | Existing compiled enum values unchanged. Source-level switch coverage concern. Value shifts caught separately. |
| Union field added | All union fields start at offset 0; existing fields unaffected. Size increase caught by TYPE_SIZE_CHANGED. |
| GLOBAL→WEAK binding | Symbol still exported and resolvable by the dynamic linker. |
| GNU IFUNC introduced/removed | Transparent to callers via PLT/GOT mechanism. |
| New/removed DT_NEEDED dependency | Deployment concern, not binary interface break. |
| RPATH/RUNPATH changed | Search path metadata, not symbol contract. |
| Toolchain flag drift | Informational — not a proven binary break on its own. |
| DWARF info missing | Coverage gap warning — comparison was incomplete. |

Some changes are classified as **BREAKING** despite being borderline, because they
can cause runtime failures in realistic deployments:

| Change | Why it's BREAKING |
|---|---|
| ELF `st_size` changed | In ELF-only mode (no headers/DWARF), may be the sole signal for vtable/variable layout changes. |
| New version requirement (e.g. GLIBC_2.34) | Library fails to load on runtimes lacking that version — hard runtime failure. |
| Typeinfo/vtable visibility change | Cross-DSO `dynamic_cast` and exception matching can fail at runtime. |
| Variable const qualifier added/removed | Adding const moves variable to `.rodata` — existing writes cause SIGSEGV. |

---

## ABI/API breakages and tool coverage

Benchmark run on all 28 examples (27 compilable). See [full benchmark report](docs/benchmark_report.md).

### Summary accuracy (27 compilable cases)

| Tool | Correct / 27 | Accuracy |
|------|-------------|----------|
| **abicheck** | **21 / 27** | **77 %** |
| **abicheck-compat** | **20 / 27** | **74 %** |
| abidiff (ELF-only) | 7 / 27 | 25 % |
| abidiff+headers | 7 / 27 | 25 % |

Legend: ✅ correct verdict, ❌ wrong verdict, — not applicable / tool skipped.

| Case | Expected | abicheck | abicheck-compat | abidiff |
|------|----------|:--------:|:---------------:|:-------:|
| case01 — Symbol removed | BREAKING | ✅ | ✅ | ✅ |
| case02 — Param type changed | BREAKING | ✅ | ✅ | ❌ |
| case03 — Compatible addition | COMPATIBLE | ✅ | ✅ | ✅ |
| case04 — No change baseline | NO_CHANGE | ❌¹ | ✅ | ✅ |
| case05 — SONAME policy break | BREAKING | ❌² | ❌² | ❌ |
| case06 — Visibility break | BREAKING | ✅ | ✅ | ✅ |
| case07 — Struct layout | BREAKING | ✅ | ✅ | ❌ |
| case08 — Enum value changed | BREAKING | ✅ | ✅ | ❌ |
| case09 — C++ vtable drift | BREAKING | ✅ | ✅ | ❌ |
| case10 — Return type changed | BREAKING | ✅ | ✅ | ❌ |
| case11 — Global var type | BREAKING | ✅ | ✅ | ❌ |
| case12 — Function removed | BREAKING | ✅ | ✅ | ✅ |
| case13 — Symbol versioning | BREAKING | ❌² | ❌² | ❌ |
| case14 — Class size changed | BREAKING | ✅ | ✅ | ❌ |
| case15 — noexcept change | COMPATIBLE | ❌³ | ❌³ | ❌ |
| case16 — inline↔non-inline | COMPATIBLE | ✅ | ✅ | ✅ |
| case17 — Template ABI drift | BREAKING | ✅ | ✅ | ❌ |
| case18 — Dependency leak | BREAKING | ✅ | ✅ | ❌ |
| case19 — Enum member removed | BREAKING | ✅ | ✅ | ❌ |
| case20 — Enum member value | BREAKING | ✅ | ✅ | ❌ |
| case21 — Method became static | BREAKING | ✅ | ✅ | ❌ |
| case22 — Method const changed | BREAKING | ✅ | ✅ | ✅ |
| case23 — Pure virtual added | BREAKING | ⏱ | ⏱ | ⏱ |
| case24 — Union field removed | BREAKING | ✅ | ✅ | ❌ |
| case25 — Enum member added | COMPATIBLE | ❌³ | ❌³ | ❌ |
| case26 — Union field added | COMPATIBLE | ❌³ | ❌³ | ✅ |
| case27 — Symbol binding weakened | COMPATIBLE | ❌³ | ❌³ | ❌ |
| case29 — IFUNC transition | COMPATIBLE | ❌³ | ❌³ | ❌ |

> ¹ Returns COMPATIBLE instead of NO_CHANGE — same practical meaning, minor verdict distinction.  
> ² ELF metadata / linker-script property outside abicheck's current detection scope.  
> ³ Conservative over-approximation: abicheck flags as BREAKING; binary ABI is compatible.  
> ⏱ case23 has intentionally unbuildable example source (abstract class factory).

### Tooling summary

- `abidiff` (ELF-only): catches symbol removal and visibility changes; misses all type-level changes.
- `abidiff + headers`: marginal improvement; requires exact header path setup.
- **abicheck / abicheck-compat**: header-aware, detects struct/enum/vtable/template changes.
  Currently over-conservative on "COMPATIBLE additions" cases (25/26/27/29).
- `ABICC (abi-dumper)`: strong DWARF pipeline when available; requires debug builds.

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
