# Coverage Report — abicheck

_Generated: 2026-03-08_

## ChangeKind Coverage: 62/62 (100%)

All 62 `ChangeKind` values now have explicit `assert c.kind == ChangeKind.X`
assertions across the test suite. `tests/test_changekind_coverage.py` adds the
previously uncovered cases that bring the suite to 62/62.

### Previously uncovered (now fixed)

| ChangeKind | Verdict | Test class |
|---|---|---|
| `FUNC_VIRTUAL_REMOVED` | BREAKING | `TestFuncVirtualRemoved` |
| `VAR_TYPE_CHANGED` | BREAKING | `TestVarTypeChanged` |
| `VAR_ADDED` | COMPATIBLE | `TestVarAdded` |
| `TYPE_REMOVED` | BREAKING | `TestTypeRemoved` |
| `TYPE_ADDED` | COMPATIBLE | `TestTypeAdded` |
| `TYPE_ALIGNMENT_CHANGED` | BREAKING | `TestTypeAlignmentChanged` |
| `TYPE_FIELD_TYPE_CHANGED` | BREAKING | `TestTypeFieldTypeChanged` |
| `TYPE_FIELD_ADDED` | BREAKING (polymorphic) | `TestTypeFieldAdded` |
| `TYPEDEF_REMOVED` | BREAKING | `TestTypedefRemoved` |
| `TYPE_VISIBILITY_CHANGED` | BREAKING | `TestTypeVisibilityChanged` |

---

## pytest-cov: Module Coverage

| Module | Stmts | Miss | Branch | BrPart | Cover |
|---|---|---|---|---|---|
| `__init__.py` | 0 | 0 | 0 | 0 | **100%** |
| `checker.py` | 478 | 13 | 204 | 12 | **96%** |
| `html_report.py` | 142 | 2 | 56 | 2 | **98%** |
| `sarif.py` | 44 | 3 | 8 | 0 | **94%** |
| `suppression.py` | 82 | 8 | 36 | 4 | **90%** |
| `model.py` | 110 | 7 | 6 | 1 | **91%** |
| `reporter.py` | 44 | 5 | 24 | 2 | **87%** |
| `serialization.py` | 66 | 12 | 10 | 1 | **80%** |
| `dwarf_advanced.py` | 230 | 54 | 106 | 25 | **72%** |
| `dwarf_metadata.py` | 306 | 118 | 130 | 32 | **56%** |
| `elf_metadata.py` | 119 | 61 | 44 | 0 | **36%** |
| `cli.py` | 132 | 132 | 40 | 0 | **0%** |
| `compat.py` | 46 | 46 | 10 | 0 | **0%** |
| `dumper.py` | 336 | 336 | 140 | 0 | **0%** |
| **TOTAL** | **2135** | **797** | **814** | **79** | **60%** |

> Test suite: 219 passed (unit + sprint tests, no external tools required)

---

## Gap Analysis by Module

### ✅ Core logic (checker, html_report, sarif) — 94–98%
Remaining misses in `checker.py` are edge guards (ELF-only path fallbacks, empty
snapshot guards, error branches). Not worth unit-testing individually.

### 🟡 suppression / reporter / serialization — 80–90%
Missing lines are error paths (invalid YAML, malformed input). Covered by
`test_suppression.py`/`test_reporter.py` partially; edge cases left.

### 🟡 dwarf_advanced.py — 72%
Missing: `parse_advanced_dwarf()` real binary paths (require `pyelftools` + `.so`
with DWARF). All diff logic covered via monkeypatching. Binary-level tests
would require integration fixtures.

### 🔴 dwarf_metadata.py — 56% / elf_metadata.py — 36%
Both parse real ELF binaries via `pyelftools`/`readelf`. Unit tests mock the
data; integration paths require compiled `.so` with debug symbols.
Covered by `test_elf_parse_integration.py` (needs `readelf` on CI).

### 🔴 cli.py / compat.py / dumper.py — 0%
These require the `abicheck` CLI binary in PATH + real `.so` files.
Covered by `test_cli_phase1.py` / `test_compat.py` / `test_dumper_phase1.py`
in integration mode (need `castxml` + `gcc`).

---

## Roadmap to 80%+ total coverage

| Priority | Action | Expected gain |
|---|---|---|
| P1 | Fix CLI test fixture: add `abicheck` to PATH in CI | +5% (cli.py) |
| P1 | Add `compat.py` unit tests with mocked checker output | +2% |
| P2 | `dwarf_metadata.py` mock-based tests for DWARF DIE parsing | +5% |
| P2 | `elf_metadata.py` tests with prebuilt minimal ELF fixtures | +3% |
| P3 | `dumper.py` snapshot serialization round-trip tests | +5% |

Estimated total after P1+P2: **~72%**. After all: **~82%**.
