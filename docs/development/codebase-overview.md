# Codebase Analysis Report -- abicheck

**Date:** 2026-03-07
**Scope:** Full repository analysis -- code patterns, logic correctness, documentation accuracy, improvement opportunities.

---

## 1. Architecture Overview

The project is a Python-based ABI compatibility checker for C/C++ shared libraries, structured in clear layers:

| Module | Role |
|--------|------|
| `model.py` | Data model (AbiSnapshot, Function, RecordType, EnumType, etc.) |
| `checker_types.py` | Core result types (Change, DiffResult, DetectorSpec) — extracted from checker.py |
| `dumper.py` | Headers + binary → AbiSnapshot via castxml + pyelftools/pefile/macholib |
| `checker.py` | Diff orchestration: delegates to sub-modules, collects changes |
| `diff_symbols.py` | Symbol-level ABI diff detectors (functions, variables, parameters) |
| `diff_types.py` | Type-level ABI diff detectors (structs, enums, unions, typedefs) |
| `diff_platform.py` | Platform-specific ABI diff detectors (ELF, PE, Mach-O, DWARF) |
| `diff_filtering.py` | Post-processing: enrichment, redundancy filtering, AST-DWARF dedup |
| `checker_policy.py` | ChangeKind enum, built-in policy profiles, verdict computation |
| `detectors.py` | Individual ABI change detection rules |
| `service.py` | Service layer — shared orchestration for CLI and MCP server |
| `reporter.py` | DiffResult → JSON / Markdown output |
| `html_report.py` | Self-contained HTML report generator |
| `sarif.py` | SARIF output for GitHub Code Scanning |
| `serialization.py` | AbiSnapshot ↔ JSON round-trip |
| `suppression.py` | YAML-based suppression rules for known changes |
| `severity.py` | Severity classification for changes |
| `binary_fingerprint.py` | Lightweight binary fingerprinting for rename detection in stripped binaries (exploratory, ADR-003 extension) |
| `elf_metadata.py` | ELF dynamic section + symbol table via pyelftools |
| `pe_metadata.py` | PE/COFF reader — Windows `.dll` binaries (via pefile) |
| `macho_metadata.py` | Mach-O reader — macOS `.dylib` binaries (via macholib) |
| `dwarf_metadata.py` | DWARF type layout extraction via pyelftools |
| `dwarf_advanced.py` | Calling convention, packing, toolchain flag drift |
| `dwarf_unified.py` | Unified DWARF handling (Linux/macOS) |
| `pdb_parser.py` | Minimal PDB parser (MSF container, TPI, DBI streams) |
| `pdb_metadata.py` | PDB debug info → DwarfMetadata/AdvancedDwarfMetadata |
| `resolver.py` | Dependency tree resolution |
| `binder.py` | Symbol binding simulation across loaded DSOs |
| `stack_checker.py` | Full-stack ABI validation across dependency trees |
| `appcompat.py` | Application compatibility checking |
| `mcp_server.py` | MCP server for AI agent integration |
| `compat/` | ABICC compatibility layer: descriptor parsing, XML report generation, CLI commands |
| `cli.py` | Click-based CLI (dump, compare, compat, deps, stack-check, appcompat) |

---

## 2. Code Quality -- Strengths

### 2.1 Well-Designed Data Model
- `model.py` uses clean dataclasses with sensible defaults
- Lazy indexing on `AbiSnapshot` (`function_map`, `variable_map`, `type_by_name`) avoids unnecessary work
- `Visibility` enum cleanly separates PUBLIC / HIDDEN / ELF_ONLY

### 2.2 Layered Detection Strategy
The checker implements four detection tiers, each adding coverage:
1. **Header/castxml layer** -- type-level ABI (struct layout, vtable, enum values)
2. **ELF-only layer** -- no debug info needed (SONAME, NEEDED, symbol binding/type/size, versioning)
3. **DWARF layout layer** -- struct sizes, field offsets from debug info
4. **Advanced DWARF** -- calling convention, packing, toolchain flags

This is architecturally sound and allows graceful degradation when debug info is absent.

### 2.3 Security Considerations
- `defusedxml` used for XML parsing (XXE prevention)
- Path traversal check in `compat/descriptor.py:_resolve()` for descriptor paths
- TOCTOU prevention via `os.fstat()` after `open()` in `elf_metadata.py`
- `yaml.safe_load()` used (not `yaml.load()`)

### 2.4 Robust DWARF Parsing
- Iterative traversal (deque-based) avoids Python recursion limits
- CU-relative vs absolute DWARF reference handling is correct
- Type resolution is memoized per parse call
- Forward declarations are properly excluded from struct name registration

### 2.5 Suppression System
- Well-designed with `fullmatch` semantics (prevents accidental over-suppression)
- Regex patterns compiled eagerly (fail at load time, not match time)
- Unknown keys rejected (catches typos)
- Audit trail preserved (suppressed changes tracked)

---

## 3. Code Issues and Improvement Opportunities

### 3.1 CRITICAL: Dual XML Parser Usage in `dumper.py`

**File:** `dumper.py:12-13`
```python
from xml.etree import ElementTree as ET          # stdlib (unsafe)
from defusedxml import ElementTree as DefusedET   # safe
```

The module imports BOTH the unsafe stdlib `xml.etree.ElementTree` and `defusedxml`. The castxml cache read path (`_castxml_dump` line 120) correctly uses `DefusedET.parse()`, but the type annotations and element creation use the stdlib `ET.Element` type. This is not a vulnerability (castxml output is trusted local data), but the dual import is confusing and violates the project's own security posture. **Recommendation:** Use `defusedxml` consistently throughout.

### 3.2 ~~`dumper.py` Uses subprocess `readelf` Despite pyelftools Migration~~ (FIXED)

The `_readelf_exported_symbols()` subprocess call has been removed. Symbol extraction
now uses pyelftools exclusively via `parse_elf_metadata()`, consistent with ADR-001.

### 3.3 ~~`_compute_verdict` Has Redundant Branch~~ (FIXED)

Verdict computation has been moved to `compute_verdict()` in `checker_policy.py` and now
uses `policy_kind_sets()` which returns policy-specific kind sets. A compile-time
completeness assertion ensures every `ChangeKind` is classified in exactly one of
`BREAKING_KINDS`, `API_BREAK_KINDS`, `COMPATIBLE_KINDS`, or `RISK_KINDS` — unclassified
kinds cause an `AssertionError` at import time (fail-safe).

### 3.4 ~~`_API_BREAK_KINDS` Is Empty and Unused~~ (FIXED)

`API_BREAK_KINDS` in `checker_policy.py` is now populated with source-level-only break
kinds (e.g. `ENUM_MEMBER_RENAMED`, `PARAM_DEFAULT_VALUE_REMOVED`, `FIELD_RENAMED`,
`PARAM_RENAMED`, `METHOD_ACCESS_CHANGED`). These produce the `API_BREAK` verdict
(exit code 2).

### 3.5 `RecordType.kind` Redundancy with `is_union`

**File:** `model.py:73-83`
```python
class RecordType:
    kind: str  # "struct" | "class" | "union"
    ...
    is_union: bool = False
```

`kind` and `is_union` encode overlapping information. `is_union` is `True` when `kind == "union"`, but they're set independently, risking inconsistency. Several places in the codebase check `is_union` while others check `kind`.

**Recommendation:** Derive `is_union` as a property: `@property def is_union(self) -> bool: return self.kind == "union"` and remove the stored field.

### 3.6 HTML Report `bc_pct` Metric Is Misleading

**File:** `html_report.py:78-85`
```python
if breaking == 0:
    bc_pct = 100.0
elif total > 0:
    bc_pct = max(0.0, (total - breaking) / total * 100)
```

This calculates "Binary Compatibility %" as `(total_changes - breaking_changes) / total_changes * 100`. This is the percentage of *changes* that are non-breaking, NOT the percentage of the API surface that remains compatible. A library with 1000 symbols and 1 breaking change would show ~0% BC if only 1 total change exists (the breaking one), which is misleading. The inline comment acknowledges this (`approx. from changed symbols, not total exported surface`), but the metric itself is still confusing.

**Recommendation:** Either compute BC% against total exported symbol count, or remove the percentage and just report counts.

### 3.7 ~~Missing `is_extern_c` Deserialization~~ (FIXED)

`is_extern_c` is now correctly deserialized in `serialization.py` via `f.get("is_extern_c", False)`.

### 3.8 ~~Inconsistent `_public()` Helper~~ (FIXED)

The unused `_public()` helper has been removed from `checker.py`. Filtering is handled inline in `_diff_functions` and `_diff_variables`.

### 3.9 ~~`_vt_sort_key` Returns Inconsistent Types~~ (FIXED)

The return type annotation has been corrected to `tuple[int, int]`.

### 3.10 ~~`RecordType` Missing `alignment_bits` Deserialization~~ (FIXED)

`alignment_bits` is now correctly deserialized in `serialization.py` via `t.get("alignment_bits")`.

---

## 4. Documentation Issues

### 4.1 ~~README Claims `re.search` but Code Uses `re.fullmatch`~~ (FIXED)

The README no longer references `re.search` for suppression patterns.

### 4.2 ~~README Uses Old CLI Name `abi-check`~~ (FIXED)

The README now consistently uses `abicheck` as the CLI command name.

### 4.3 ~~Goals Exit Code Documentation is Wrong~~ (FIXED)

[Goals](goals.md) now documents the correct exit codes:
- `compare` command: 0 = compatible/no_change, 2 = source break, 4 = breaking ABI change
- `compat` command: 0 = compatible/no_change, 1 = breaking, 2 = error

### 4.4 ~~Goals Claims ABICC and libabigail Are Unmaintained~~ (FIXED)

[Goals](goals.md) has been updated. It now correctly states that
ABICC is no longer actively maintained while libabigail is maintained by Red Hat but
focuses on DWARF-only analysis.

### 4.5 ~~`pyproject.toml` Description Says "castxml-based"~~ (FIXED)

The description has been updated to "ABI compatibility checker for C/C++ shared libraries",
reflecting the multi-tier detection approach (binary metadata, header AST, debug info).

### 4.6 `gap_report.md` Phase Status Is Stale

The gap report listed roadmap/TODO items that have now been implemented:
-  10 detection gaps -- all implemented and tested
-  ELF-only detectors -- all implemented
-  DWARF layout -- implemented
-  Advanced DWARF -- implemented

### 4.7 ~~`__init__.py` Module Docstring Uses Old Name~~ (FIXED)

The docstring now reads `"""abicheck — ABI compatibility checker."""`.

---

## 5. Testing Gaps

### 5.1 ~~No Error/Edge Case Tests~~ (PARTIALLY ADDRESSED)
- `test_adversarial_inputs.py` and `test_error_handling.py` now cover corrupted inputs and failure paths
- `test_castxml_errors.py` covers castxml failure modes
- Remaining gaps: malformed DWARF info, circular typedef chains, very large symbol counts

### 5.2 ~~Missing Negative Tests~~ (ADDRESSED)
`test_negative.py` now verifies that benign changes are NOT flagged as breaking.

### 5.3 ~~No Backward Compatibility Tests for Serialization~~ (ADDRESSED)
`test_serialization_roundtrip.py` and `test_snapshot_roundtrip.py` now verify round-trip fidelity.

### 5.4 `test_abi_examples.py` Silently Skips
Integration tests skip silently when castxml/gcc aren't installed, which could mask real failures in CI.

### 5.5 HTML Report Not Tested for XSS
`html_report.py` uses `html.escape()` correctly, but no test verifies that malicious symbol names (containing `<script>` tags) are properly escaped in the output.

### 5.6 Parity Test Coverage Expanding
`test_abidiff_parity.py` covers 10 cases; additional parity suites (`test_abicc_parity.py`,
`test_abicc_full_parity.py`, `test_sprint7_full_parity.py`, `test_sprint10_abicc_parity.py`)
bring total parity coverage to ~54 test functions.

---

## 6. Suggested Priority Improvements

### P0 -- Correctness (all resolved)
1. ~~**Fix `is_extern_c` deserialization**~~ — done
2. ~~**Fix `alignment_bits` deserialization**~~ — done
3. ~~**Fix README `re.search` vs `re.fullmatch` documentation**~~ — done
4. ~~**Fix README CLI name** `abi-check` → `abicheck`~~ — done
5. ~~**Fix `_compute_verdict` fallback**~~ — done (import-time assertion + policy-aware verdict)

### P1 -- Technical Debt (mostly resolved)
6. ~~**Remove `_readelf_exported_symbols`**~~ — done (pyelftools only)
7. ~~**Remove unused `_public()` helper**~~ — done
8. **Unify `RecordType.kind` and `is_union`** to prevent inconsistency — open
9. ~~**Update `__init__.py` docstring**~~ — done
10. ~~**Update `docs/development/goals.md` exit codes**~~ — done

### P2 -- Test Coverage
11. Add negative tests (benign changes should not be flagged) — `test_negative.py` added
12. Add error handling tests (corrupted inputs) — `test_adversarial_inputs.py`, `test_error_handling.py` added
13. Add serialization backward-compatibility tests — `test_serialization_roundtrip.py` added
14. Expand parity test suite to match gap report scope — ongoing

### P3 -- Documentation (mostly resolved)
15. ~~**Update `gap_report.md` status text**~~ — done
16. ~~**Fix `docs/development/goals.md` claim about libabigail**~~ — done
17. ~~**Update `pyproject.toml` description**~~ — done
