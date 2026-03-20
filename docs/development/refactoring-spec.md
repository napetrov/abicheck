# Refactoring Specification

**Created:** 2026-03-20
**Scope:** ~2,500 lines moved/refactored across 4 phases
**Risk profile:** All changes are internal refactors — no public API changes,
no new features, no behavior changes.

## Phase 1: Break the Circular Dependency & Clean Up Types ✅

**Goal:** Move `Change` out of `checker.py` so that `suppression.py` no longer
needs a TYPE_CHECKING import from `checker`. This unblocks the Phase 2 split.

**Issues addressed:** Circular import (6.6), unused Detector protocol (6.4)

### Changes Made

- **New file:** `abicheck/checker_types.py` — contains `Change`, `DiffResult`,
  `LibraryMetadata`, and `DetectorSpec` dataclasses
- **`detectors.py`:** Removed unused `Detector` protocol class, kept
  `ChangeLike` and `DetectorResult`
- **`suppression.py`:** Now imports from `checker_types` directly (no more
  TYPE_CHECKING guard)
- **`checker.py`:** Imports and re-exports from `checker_types` for backward
  compatibility; `_DetectorSpec` aliased to `DetectorSpec`

## Phase 2: Split checker.py Into Focused Modules ✅

**Goal:** Reduce `checker.py` from ~3,830 lines to ~500 lines by extracting
detection and filtering logic into dedicated modules.

**Issue addressed:** checker.py monolith (6.2)

### Extracted Modules

| Module | Contents | Lines |
|--------|----------|-------|
| `diff_symbols.py` | Function/variable/parameter detectors | ~670 |
| `diff_types.py` | Type/struct/enum/union/typedef detectors | ~915 |
| `diff_platform.py` | ELF/PE/Mach-O/DWARF platform detectors | ~1,205 |
| `diff_filtering.py` | Redundancy filtering, deduplication | ~1,002 |
| `checker.py` (remaining) | Orchestration + detector registry | ~340 |

## Phase 3: Extract Service Layer ✅

**Goal:** Create `service.py` as the shared orchestration layer consumed by
both `cli.py` and `mcp_server.py`, eliminating duplicated business logic.

**Issue addressed:** Missing service layer (6.1)

### Implemented API

- `resolve_input()` — Load an ABI snapshot from any supported input format
- `run_dump()` — Extract ABI snapshot from a binary + optional headers
- `run_compare()` — Compare two ABI snapshots and return classified changes
- `render_output()` — Render a DiffResult to the specified output format

### Additional Functions

- `detect_binary_format()` — Detect ELF/PE/Mach-O from magic bytes
- `sniff_text_format()` — Detect JSON/Perl dump from header bytes
- `expand_header_inputs()` — Recursively expand header file/directory inputs
- `collect_metadata()` — Compute SHA-256 and file size for traceability
- `load_suppression_and_policy()` — Load suppression and policy YAML files

## Phase 4: Error Handling Standardization ✅

**Goal:** Replace raw `ValueError`/`RuntimeError` with the custom exception
hierarchy from `errors.py`.

**Issues addressed:** Inconsistent error handling (6.3), xml import (6.7)

### Changes Made

- **`errors.py`:** Added `PolicyError` and `ReportError`; made `ValidationError`
  inherit `ValueError`, `SnapshotError` inherit `RuntimeError`, `PolicyError`
  inherit `ValueError` for backward compatibility
- **Migrated ~46 exception sites** across 8 modules:
  - `dumper.py`: RuntimeError → SnapshotError, ValueError → ValidationError
  - `pdb_parser.py`: ValueError → ValidationError
  - `package.py`: RuntimeError → SnapshotError
  - `policy_file.py`: ValueError → PolicyError
  - `severity.py`: ValueError → PolicyError
  - `compat/abicc_dump_import.py`: ValueError → ValidationError
  - `compat/descriptor.py`: ValueError → ValidationError
- **Zero test file changes** required (backward-compatible inheritance)

## Execution Order

```
Phase 1 ──→ Phase 2 ──→ (done)
    │
    └─────→ Phase 3 ──→ (done)

Phase 4 ─────────────→ (done, independent)
```

## Invariants (Must Hold After Every Phase)

1. `pytest tests/` passes with zero test file changes
2. `mypy abicheck/` passes with zero new errors
3. `ruff check abicheck/` passes
4. All public imports from `abicheck.checker` continue to work
5. CLI output is byte-identical for all supported formats
6. Exit codes unchanged for all command modes
7. No new dependencies added to `pyproject.toml`
