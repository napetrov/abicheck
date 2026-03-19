# Consolidation Specification

**Date:** 2026-03-19
**Based on:** CODE_DUPLICATION_ANALYSIS.md (post-review revision)
**Goal:** Eliminate confirmed code duplication across 28 issues, prioritized by impact and risk.

---

## Phased Approach

Consolidation is organized into **4 phases**, ordered by risk (lowest first) and dependency (foundations before consumers). Each phase is independently shippable and testable.

---

## Phase 1: Zero-Risk Imports (html_report.py cleanup)

**Issues addressed:** #1 (classification constants), #24 (dead `_CHANGED_BREAKING_KINDS`)
**Estimated lines removed:** ~130
**Risk:** None — behavioral equivalence confirmed by review
**Test coverage:** `test_report_classifications_unit.py` (22 tests) validates the canonical module

### Step 1.1: Delete dead code

Remove `_CHANGED_BREAKING_KINDS` from `html_report.py` (L86-124). Confirmed unreferenced by any function in the file.

### Step 1.2: Replace constants with imports

In `html_report.py`, replace all private constant definitions with imports from `report_classifications`:

```python
from .report_classifications import (
    REMOVED_KINDS,
    ADDED_KINDS,
    BREAKING_KINDS,
    CATEGORY_PREFIXES,
    HIGH_SEVERITY_KINDS,
    MEDIUM_SEVERITY_KINDS,
)
```

Update all internal references from `_REMOVED_KINDS` → `REMOVED_KINDS`, etc.

### Step 1.3: Replace helper functions with imports

Replace the 6 duplicated private functions with imports:

```python
from .report_classifications import (
    category,
    severity,
    is_breaking,
    kind_str,
    is_type_problem,
    is_symbol_problem,
)
```

Delete the private function definitions `_category`, `_severity`, `_is_breaking`, `_kind_str`, `_is_type_problem`, `_is_symbol_problem`. Update all call sites within `html_report.py` to use the imported names (drop the `_` prefix).

Note: `_change_bucket` (L173) has no counterpart in `report_classifications.py` and should remain in `html_report.py`.

### Step 1.4: Unify element-kind classification

Move `ShowOnlyFilter.matches()` in `reporter.py` (L120-148) to use `CATEGORY_PREFIXES` from `report_classifications.py` instead of its own hardcoded prefix tuples. This addresses issue #23.

### Verification

- Run existing `test_report_classifications_unit.py`
- Run any integration tests that generate HTML reports and diff the output
- Grep for removed symbol names to confirm no dangling references

---

## Phase 2: Shared DWARF Utilities (dwarf_utils.py enrichment)

**Issues addressed:** #2 (type resolution), #4 (member location decoding), #6 (qualifier unwrapping), #7 (inline ref resolution), #15 (skip-tag constants)
**Estimated lines removed:** ~200
**Risk:** Medium — DWARF parsing is correctness-critical
**Test coverage:** `test_dwarf_metadata_coverage.py` (64 tests), `test_dwarf_snapshot.py` (82 tests)

### Step 2.1: Add base prune-tag constant

Add to `dwarf_utils.py`:

```python
BASE_PRUNE_TAGS: frozenset[str] = frozenset({
    "DW_TAG_inlined_subroutine",
    "DW_TAG_lexical_block",
    "DW_TAG_GNU_call_site",
})
```

Update `dwarf_metadata.py` (`_SKIP_TAGS`), `dwarf_advanced.py` (`_PRUNE_TAGS`), and `dwarf_snapshot.py` (inline tuple) to compose from this base. Each module adds its own entries (e.g., `dwarf_metadata.py` adds `DW_TAG_subprogram`).

### Step 2.2: Move `_evaluate_location_expr` to dwarf_utils.py

Move the full stack-machine implementation from `dwarf_snapshot.py` (L171-237) to `dwarf_utils.py` as `decode_member_location(val)`:

```python
def decode_member_location(val: int | list | None) -> int:
    """Decode DW_AT_data_member_location to a byte offset."""
    if val is None:
        return 0
    if isinstance(val, int):
        return val
    return _evaluate_location_expr(val)
```

Update all three callers:
- `dwarf_metadata.py` `_process_member` (L389-397): replace naive `val[-1]` with `decode_member_location(val)`
- `dwarf_advanced.py` `_decode_member_location` (L587-615): replace with call to `decode_member_location`
- `dwarf_snapshot.py` `_process_field` (L598-605): replace with call to `decode_member_location`

### Step 2.3: Extract shared type resolver

Create `resolve_dwarf_type(die, cu, cache, depth=0) -> tuple[str, int]` in `dwarf_utils.py`, extracted from `dwarf_snapshot.py` `_compute_type_name` (the more complete version).

Update both callers:
- `dwarf_metadata.py`: replace `_die_to_type_info`/`_compute_type_info` with calls to the shared resolver
- `dwarf_snapshot.py`: replace `_die_to_type_name`/`_compute_type_name` with calls to the shared resolver

### Step 2.4: Fix inline reference resolution in dwarf_advanced.py

Replace inline ref resolution at lines 210-213 and 523-526 with calls to existing `dwarf_utils.resolve_die_ref`.

### Step 2.5: Consolidate qualifier unwrapping in dwarf_advanced.py

Make `_get_type_align` (L217-232) call `_unwrap_qualifiers` (L395-424) instead of reimplementing the unwrapping loop.

### Verification

- Run `test_dwarf_metadata_coverage.py` (64 tests)
- Run `test_dwarf_snapshot.py` (82 tests)
- Run full example validation suite (`test_abi_examples.py`) to catch regressions
- Verify DWARF parsing output is byte-identical for a representative sample of shared libraries

### NOT in scope (confirmed by review)

- **DIE traversal patterns** (#14): Intentionally different. Do NOT consolidate.
- **ELF open boilerplate** (#16): `dwarf_unified.py` is an I/O optimization wrapper, not a replacement. Architecture is intentional.
- **Struct/enum processing** (#5): Different output data models (`FieldInfo` vs `TypeField`). Requires intermediate representation design — defer to future work.
- **Typedef-to-anonymous resolution** (#19): Tightly coupled to struct/enum processing. Defer with #5.

---

## Phase 3: Binary Format Detection & Stack Module Cleanup

**Issues addressed:** #3 (binary detection), #11 (loadability duplication), #12 (appcompat duplication), #25 (bindings summary), #18 (graph-to-dict helpers)
**Estimated lines removed:** ~100
**Risk:** Low-Medium
**Test coverage:** `test_appcompat.py` (86 tests), `test_stack_checker.py` (55 tests)

### Step 3.1: Create shared `detect_binary_format()`

Create a new utility function (suggest placing in `elf_metadata.py` or a new `binary_utils.py`):

```python
_MACHO_MAGICS: frozenset[bytes] = frozenset({
    b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe",  # 32-bit
    b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe",  # 64-bit
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",  # fat archive 32
    b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",  # fat archive 64
})

def detect_binary_format(path: str | Path) -> str | None:
    """Detect binary format from file magic bytes. Returns 'elf', 'pe', 'macho', or None."""
    try:
        with open(path, "rb") as f:
            magic = f.read(4)
    except (OSError, IOError):
        return None
    if magic[:4] == b"\x7fELF":
        return "elf"
    if magic[:2] == b"MZ":
        return "pe"
    if magic[:4] in _MACHO_MAGICS:
        return "macho"
    return None
```

Update callers:
- `appcompat.py` `_detect_app_format` → call shared function (keep `S_ISREG` check locally if needed)
- `cli.py` `_detect_binary_format` → call shared function (delete `_is_elf`, `_is_pe`, `_is_macho`)
- `mcp_server.py` `_detect_binary_format` → call shared function

### Step 3.2: Fix loadability duplication in stack_checker.py

Replace `check_single_env()` lines 207-214 with:
```python
loadability = _compute_loadability(graph, missing, version_mismatches)
```

Drop-in replacement confirmed by review.

### Step 3.3: Extract shared symbol-checking logic in appcompat.py

Extract the duplicated missing-symbol/version-mismatch collection from `check_appcompat()` and `check_against()` into a private `_check_symbol_coverage()` function within the same file.

### Step 3.4: Extract graph serialization helpers

In `stack_report.py`, extract `_node_to_dict(node)` and `_edge_to_dict(edge)` as module-level helpers. Have `cli.py` import them instead of duplicating.

### Step 3.5: Deduplicate bindings summary counting

Extract bindings summary counting into a shared function in `stack_report.py`. Have `cli.py` call it.

### Verification

- Run `test_appcompat.py` (86 tests)
- Run `test_stack_checker.py` + `test_stack_checker_unit.py` (55 tests)
- Run CLI integration tests
- Run MCP server tests

---

## Phase 4: PDB/PE Module Cleanup

**Issues addressed:** #8 (forward-ref filtering), #9 (double iteration), #10 (PE open ceremony), #13 (forward-ref passes), #20 (_parse_struct/_parse_union), #21 (PdbFileName), #22 (machine types), #28 (private `_bitfields` access)
**Estimated lines removed:** ~80
**Risk:** Low (Windows-specific modules, isolated changes)
**Test coverage:** PDB/PE tests exist but were not enumerated

### Step 4.1: Extract `_is_user_visible()` predicate in pdb_metadata.py

```python
def _is_user_visible(name: str | None, is_forward_ref: bool) -> bool:
    if is_forward_ref:
        return False
    if not name:
        return False
    if name.startswith("<") or name.startswith("__"):
        return False
    return True
```

Replace the 3 inline guard blocks.

### Step 4.2: Fold `_extract_calling_conventions` into `_extract_struct_layouts`

Collect `adv.all_struct_names` and `adv.packed_structs` during the existing struct iteration pass, eliminating the redundant second pass.

### Step 4.3: Consolidate `_parse_struct` and `_parse_union` in pdb_parser.py

Merge into `_parse_record(data, offset, is_union: bool)`.

### Step 4.4: Extract PdbFileName decoding helper in pdb_utils.py

```python
def _decode_pdb_filename(data: Any) -> str | None:
    if not hasattr(data, "PdbFileName"):
        return None
    fname = data.PdbFileName
    if isinstance(fname, bytes):
        return fname.rstrip(b"\x00").decode("utf-8", errors="replace")
    return str(fname)
```

### Step 4.5: Reduce forward-ref resolution passes in pdb_parser.py

Combine struct and enum iterations: collect definitions and link forward refs in 2 passes total (one for structs, one for enums) instead of 4.

### Step 4.6: Add `get_bitfield()` public API to pdb_parser.py

Add `TypeDatabase.get_bitfield(ti: int) -> CvBitfield | None` method. Update `pdb_metadata.py` L171 to use it instead of accessing `types._bitfields` directly.

### Step 4.7: Unify machine type constants

Remove `_MACHINE_NAMES` from `pdb_metadata.py` and use `pefile.MACHINE_TYPE` (or a shared constant).

### Verification

- Run all PDB/PE related tests
- Test on representative Windows DLL samples

---

## Deferred Items (Future Work)

These items were identified but deemed not worth immediate action:

| # | Issue | Reason for Deferral |
|---|---|---|
| #5 | Struct/enum DWARF processing | Different output data models; requires intermediate representation design |
| #14 | DIE traversal consolidation | Intentionally different implementations (confirmed by review) |
| #16 | ELF open boilerplate | Architectural choice; `dwarf_unified.py` is an optimization wrapper |
| #17 | DiffResult recomputation | Negligible real-world impact; mutation hazard makes caching fragile |
| #19 | Typedef-to-anonymous resolution | Tightly coupled to #5 |
| #24 | `_VERDICT_LABEL` redundancy | Trivial; can be done opportunistically |
| #26 | Adjacency-list construction | Modest duplication; could add method to `DependencyGraph` |
| #27 | `_find_resolved_key` linear scan | Practically insignificant (small graphs, I/O dominated) |

---

## Implementation Guidelines

### Branch Strategy
- One branch per phase
- Each phase is a single PR with all steps as atomic commits
- Phases can be developed in parallel but should be merged in order

### Testing Requirements
- All existing tests must pass after each step (not just each phase)
- For Phase 2 (DWARF), run the full example validation suite
- No new test files required for import-only changes (Phase 1)
- New unit tests required for new shared functions (`decode_member_location`, `resolve_dwarf_type`, `detect_binary_format`, `_is_user_visible`)

### Code Review Checklist
- [ ] No behavioral changes in report output (HTML, Markdown, JSON, SARIF)
- [ ] All `grep` for removed function/constant names returns zero hits
- [ ] No circular imports introduced
- [ ] Type annotations preserved on shared functions
- [ ] Docstrings transferred from best-documented source

### Estimated Total Effort
| Phase | Steps | Lines Removed | Effort |
|-------|-------|---------------|--------|
| Phase 1 | 4 | ~130 | 1-2 hours |
| Phase 2 | 5 | ~200 | 3-4 hours |
| Phase 3 | 5 | ~100 | 2-3 hours |
| Phase 4 | 7 | ~80 | 2-3 hours |
| **Total** | **21** | **~510** | **8-12 hours** |

Note: Line removal estimate is lower than the analysis report (~620) because some consolidation adds shared code while removing duplicates. Net reduction accounts for the new shared implementations.
