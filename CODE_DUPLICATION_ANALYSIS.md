# Code Duplication & Inefficiency Analysis

**Date:** 2026-03-19
**Scope:** All 41 source modules in `abicheck/`

---

## Executive Summary

Analysis identified **28 distinct duplication/inefficiency issues** across the codebase, categorized by severity. The most impactful are: (1) classification constants duplicated between `html_report.py` and `report_classifications.py` (~130 lines), (2) DWARF type resolution logic duplicated across three modules (~200 lines), and (3) binary format detection implemented three separate times.

---

## High Severity

### 1. Classification Constants Duplicated Between html_report.py and report_classifications.py

`report_classifications.py` was explicitly created (line 17-18) to "avoid maintaining duplicate definitions," yet `html_report.py` redefines **every single constant** as a private copy:

| html_report.py | report_classifications.py |
|---|---|
| `_REMOVED_KINDS` (L60-69) | `REMOVED_KINDS` (L29-33) |
| `_ADDED_KINDS` (L72-83) | `ADDED_KINDS` (L36-40) |
| `_CHANGED_BREAKING_KINDS` (L86-124) | `CHANGED_BREAKING_KINDS` (L64-84) |
| `_CATEGORY_PREFIXES` (L134-152) | `CATEGORY_PREFIXES` (L128-135) |
| `_HIGH_SEVERITY_KINDS` (L465-483) | `HIGH_SEVERITY_KINDS` (L90-97) |
| `_MEDIUM_SEVERITY_KINDS` (L485-509) | `MEDIUM_SEVERITY_KINDS` (L99-111) |
| `_BREAKING_KINDS` (L129-131) | `BREAKING_KINDS` (L61) |

Additionally, **6 helper functions** are duplicated between the two files:
- `_category()` / `category()` — prefix-match to category label
- `_severity()` / `severity()` — High/Medium/Low from kind string
- `_is_breaking()` / `is_breaking()` — kind in BREAKING_KINDS
- `_kind_str()` / `kind_str()` — extract .value from change kind
- `_is_type_problem()` / `is_type_problem()` — prefix match
- `_is_symbol_problem()` / `is_symbol_problem()` — prefix match

**Fix:** `html_report.py` should import from `report_classifications.py` (as `compat/xml_report.py` already does). ~130 lines of pure duplication.

### 2. DWARF Type Resolution Logic Duplicated Across Modules

The type-resolution machinery is implemented **twice** with nearly identical logic:

- **`dwarf_metadata.py`**: `_resolve_type` (L481-493), `_die_to_type_info` (L496-517), `_compute_type_info` (L520-558)
- **`dwarf_snapshot.py`**: `_resolve_type` (L806-814), `_die_to_type_name` (L816-829), `_compute_type_name` (L831-895)

Both use the same caching strategy `(CU.cu_offset, die.offset)`, same depth limit of 8, same tag-by-tag dispatch for all DWARF type tags. ~120 lines duplicated.

**Fix:** Extract a shared `DwarfTypeResolver` into `dwarf_utils.py`.

### 3. DIE Traversal Pattern Duplicated 3 Times

Three files implement nearly identical iterative depth-first DIE traversal with a `deque`-based stack, scope tracking, and the same skip-tag filtering:

- `dwarf_metadata.py` `_walk_die_iter` (L190-235)
- `dwarf_advanced.py` `_walk_cu` (L257-297)
- `dwarf_snapshot.py` `_process_cu` (L314-355)

**Fix:** Extract shared `walk_dies()` generator into `dwarf_utils.py`.

### 4. Binary Format Detection Implemented 3 Times

- `appcompat.py:87-113` — `_detect_app_format()`: single file open, checks ELF/PE/Mach-O magic
- `cli.py:95-127` — `_detect_binary_format()`: three separate file opens (least efficient)
- `mcp_server.py:220-240` — `_detect_binary_format()`: single file open (most efficient)

**Fix:** Create a single `detect_binary_format()` function in a shared utility module.

### 5. DW_AT_data_member_location Decoding Duplicated 3 Times

- `dwarf_metadata.py` `_process_member` (L389-397) — naive `val[-1]` shortcut
- `dwarf_advanced.py` `_decode_member_location` (L587-615) — partial DW_OP decoding
- `dwarf_snapshot.py` `_process_field` (L598-605) + `_evaluate_location_expr` (L171-237) — full stack machine

**Fix:** Single `decode_member_location()` in `dwarf_utils.py`.

---

## Medium Severity

### 6. DiffResult Property Recomputation

`checker.py` `DiffResult` (L145-194): four properties (`breaking`, `source_breaks`, `compatible`, `risk`) each independently call `_effective_kind_sets()`, which rebuilds frozensets and linearly scans `self.changes`. When `reporter.to_markdown()` and `report_summary.build_summary()` access all four, it triggers **8 separate** recomputations + O(n) scans.

**Fix:** Memoize `_effective_kind_sets()` or compute all four lists in a single pass.

### 7. Struct/Record and Enum Processing Duplicated Between DWARF Modules

- Struct processing: `dwarf_metadata.py` `_process_struct` (L270-336) vs `dwarf_snapshot.py` `_process_record_type` (L516-585) — same ODR dedup, same child iteration, same field extraction pattern
- Enum processing: `dwarf_metadata.py` `_process_enum` (L429-467) vs `dwarf_snapshot.py` `_process_enum` (L659-695) — same DW_TAG_enumerator iteration

### 8. Qualifier Unwrapping Duplicated Within dwarf_advanced.py

- `_unwrap_qualifiers` (L395-424) — standalone function with depth limit 12 and caching
- `_get_type_align` (L217-232) — inline loop with depth limit 4 doing the same unwrapping

### 9. Inline Reference Resolution Ignores Existing Utility

`dwarf_advanced.py` reimplements `dwarf_utils.resolve_die_ref` logic inline at lines 210-213 and 523-526, despite importing the utility.

### 10. Forward-Ref/Anonymous Filtering Repeated 3 Times in pdb_metadata.py

Lines 123-129, 198-202, and 243-246 all repeat:
```python
if cv_struct.is_forward_ref: continue
if not cv_struct.name: continue
if cv_struct.name.startswith("<") or cv_struct.name.startswith("__"): continue
```

**Fix:** Extract `_is_user_visible(name, is_forward_ref)` predicate.

### 11. Redundant Double Iteration Over all_structs() in pdb_metadata.py

`_extract_struct_layouts` (L122) and `_extract_calling_conventions` (L243) both iterate `types.all_structs().items()`. The second pass could be folded into the first.

### 12. PE Open/Parse/Close Ceremony Duplicated

`pdb_utils.py` (L182-240) and `pe_metadata.py` (L126-201) both open/parse/close PE files independently. When processing a DLL, the same PE is parsed twice from disk.

### 13. Loadability Logic Duplicated Inline in stack_checker.py

`check_single_env()` (L207-214) re-implements the cascade of checks already in `_compute_loadability()` (L70-82) in the same file instead of calling it.

### 14. Graph-to-Dict Serialization Duplicated

`stack_report.py` (L192-200) and `cli.py` (L417-425) build identical node dicts. `cli.py` should call the `stack_report` function.

### 15. Missing-Symbol/Version-Mismatch Collection Duplicated in appcompat.py

`check_appcompat()` (L521-536) and `check_against()` (L600-614) share ~20 lines of nearly verbatim symbol/version checking logic within the same file.

### 16. `_find_resolved_key` Linear Scan in resolver.py

`resolver.py` L410-415: linear scan of all graph nodes on every revisited soname in BFS. Should use an O(1) `soname -> key` dict.

### 17. Forward-Ref Resolution Uses 4 Passes in pdb_parser.py

`pdb_parser.py` L661-673: iterates structs twice and enums twice (collection + linking). Can be done in 2 passes or even 1 combined pass.

---

## Low Severity

### 18. Skip/Prune Tag Sets Defined 3 Times

- `dwarf_metadata.py` L123-128: `_SKIP_TAGS`
- `dwarf_advanced.py` L101-105: `_PRUNE_TAGS`
- `dwarf_snapshot.py` L327-329: inline tuple

**Fix:** Single `PRUNE_TAGS` constant in `dwarf_utils.py`.

### 19. ELF Open/DWARF Check Boilerplate Appears 4 Times

`dwarf_metadata.py`, `dwarf_advanced.py`, `dwarf_snapshot.py`, and `dwarf_unified.py` each independently open ELF files and check for DWARF info.

### 20. Typedef-to-Anonymous-Type Resolution Duplicated

`dwarf_metadata.py` `_process_typedef` (L238-263) and `dwarf_snapshot.py` `_process_typedef` (L701-737) — nearly identical logic.

### 21. `_parse_struct` / `_parse_union` Near-Identical in pdb_parser.py

Lines 703-720 and 722-738 are near-duplicates differing only in struct format string and `is_union` flag. Could be a single method with a parameter.

### 22. PdbFileName Extraction Repeated Verbatim in pdb_utils.py

Lines 221-226 (RSDS branch) and 229-232 (NB10 branch) contain identical 5-line blocks for decoding `PdbFileName`.

### 23. Machine Type Constants Defined in Two Places

`pdb_metadata.py` L56-63 defines `_MACHINE_NAMES` dict; `pe_metadata.py` L140-142 uses `pefile.MACHINE_TYPE`. Should share one approach.

### 24. Element-Kind Classification Logic in 3 Places

`reporter.py` `ShowOnlyFilter.matches()` (L120-148), `html_report.py` `_CATEGORY_PREFIXES`, and `report_classifications.py` `CATEGORY_PREFIXES` — three independent prefix-to-category mappings that can diverge.

### 25. `_VERDICT_LABEL` Dict is Redundant

`reporter.py` L36-50: `_VERDICT_LABEL` maps Verdict enum members to strings, but `Verdict` is a `str` Enum where `.value` already gives the label.

### 26. Bindings Summary Counting Duplicated

`stack_report.py` (L213-219) and `cli.py` (L407-409) both count bindings by status identically.

### 27. Adjacency-List Construction Duplicated

`binder.py` (L142-146) and `stack_report.py` (L235-240) both build `adj: dict[str, list[str]]` from `graph.edges`.

### 28. Private `_bitfields` Access from Outside pdb_parser.py

`pdb_metadata.py` L171 accesses `types._bitfields.get(member.type_ti)` directly, breaking encapsulation. A public `get_bitfield(ti)` method should be added.

---

## Estimated Impact of Fixes

| Priority | Issues | Est. Lines Saved | Effort |
|----------|--------|------------------|--------|
| High | #1-5 | ~400 lines | Medium |
| Medium | #6-17 | ~200 lines | Medium |
| Low | #18-28 | ~100 lines | Low |
| **Total** | **28** | **~700 lines** | |

The high-priority items (#1-5) represent the most impactful consolidation opportunities, reducing maintenance burden and risk of divergence between duplicated definitions.
