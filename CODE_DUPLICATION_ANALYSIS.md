# Code Duplication & Inefficiency Analysis

**Date:** 2026-03-19
**Revised:** 2026-03-19 (post-review)
**Scope:** All 41 source modules in `abicheck/`

---

## Executive Summary

Analysis identified **28 distinct duplication/inefficiency issues** across the codebase. After critical review, **3 items were reclassified** (DIE traversal downgraded from High to Low due to intentional differences; DiffResult recomputation downgraded from Medium to Low as a negligible real-world impact; graph-to-dict corrected as partial overlap, not full duplication). The review also confirmed **`_CHANGED_BREAKING_KINDS` in html_report.py is dead code** — never referenced by any function.

The most impactful consolidation targets are: (1) classification constants between `html_report.py` and `report_classifications.py` (~130 lines, zero-risk), (2) DWARF type resolution across modules (~120 lines), and (3) binary format detection in three files.

---

## High Severity

### 1. Classification Constants Duplicated Between html_report.py and report_classifications.py

**Confidence: CONFIRMED — zero-risk consolidation.**

`report_classifications.py` was explicitly created (line 17-18) to "avoid maintaining duplicate definitions," yet `html_report.py` redefines **every single constant** as a private copy. `compat/xml_report.py` already imports from `report_classifications.py` correctly — `html_report.py` was never migrated.

| html_report.py | report_classifications.py | Identical? |
|---|---|---|
| `_REMOVED_KINDS` (L60-69) | `REMOVED_KINDS` (L29-33) | Yes |
| `_ADDED_KINDS` (L72-83) | `ADDED_KINDS` (L36-40) | Yes |
| `_CHANGED_BREAKING_KINDS` (L86-124) | `CHANGED_BREAKING_KINDS` (L64-84) | **No** — html_report includes `enum_last_member_value_changed` |
| `_CATEGORY_PREFIXES` (L134-152) | `CATEGORY_PREFIXES` (L128-135) | Yes |
| `_HIGH_SEVERITY_KINDS` (L465-483) | `HIGH_SEVERITY_KINDS` (L90-97) | Yes |
| `_MEDIUM_SEVERITY_KINDS` (L485-509) | `MEDIUM_SEVERITY_KINDS` (L99-111) | Yes |
| `_BREAKING_KINDS` (L129-131) | `BREAKING_KINDS` (L61) | Yes |

**Review finding:** `_CHANGED_BREAKING_KINDS` in `html_report.py` is **dead code** — no function in the file references it. The one difference between the constants is therefore irrelevant. All 6 duplicated helper functions (`_category`, `_severity`, `_is_breaking`, `_kind_str`, `_is_type_problem`, `_is_symbol_problem`) are **behaviorally identical** to their `report_classifications.py` counterparts.

**Fix:** Replace all private constants/helpers in `html_report.py` with imports from `report_classifications.py`. Delete the dead `_CHANGED_BREAKING_KINDS`. ~130 lines removed, zero behavioral risk.

### 2. DWARF Type Resolution Logic Duplicated Across Modules

**Confidence: CONFIRMED — accidental duplication with identical return types.**

- **`dwarf_metadata.py`**: `_compute_type_info` (L520-558) returns `tuple[str, int]`
- **`dwarf_snapshot.py`**: `_compute_type_name` (L831-895) returns `tuple[str, int]`

Both use the same caching strategy `(CU.cu_offset, die.offset)`, same depth limit of 8, same tag-by-tag dispatch. The review confirmed these return **identical data structures** — the duplication arose from incremental sprint development (Sprint 3 vs later), not intentional design.

**Fix:** Extract a shared `resolve_dwarf_type()` into `dwarf_utils.py`. ~120 lines saved.

### 3. Binary Format Detection Implemented 3 Times

**Confidence: CONFIRMED with nuances.**

| Location | File opens | Mach-O magics | Extra checks |
|---|---|---|---|
| `appcompat.py:87-113` | 1 | 8 (most complete) | `stat.S_ISREG` |
| `cli.py:95-127` | Up to 3 (least efficient) | Delegates to `macho_metadata` | None |
| `mcp_server.py:220-240` | 1 | 6 (missing 2 fat-archive variants) | None |

**Review finding:** The implementations are **not identical** — they differ in Mach-O magic coverage and file-open patterns. `mcp_server.py` is missing two fat-archive magic variants. `cli.py` opens the file up to 3 times unnecessarily.

**Fix:** Create `detect_binary_format()` in a shared module, using `appcompat.py`'s implementation as the base (most complete). All three callers import it. ~60 lines saved.

### 4. DW_AT_data_member_location Decoding Duplicated 3 Times

**Confidence: CONFIRMED — different quality levels are NOT intentional.**

The three implementations exist at different quality levels that correlate with when they were written (sprint order), not intentional design:
- `dwarf_metadata.py`: naive `val[-1]` shortcut (Sprint 3, earliest)
- `dwarf_advanced.py`: partial DW_OP decoding (Sprint 4)
- `dwarf_snapshot.py`: full stack machine — `_evaluate_location_expr` (L171-237, most complete)

**Fix:** Move `_evaluate_location_expr` to `dwarf_utils.py` as `decode_member_location()`. All three callers use it. ~80 lines saved, correctness improved for `dwarf_metadata.py`.

---

## Medium Severity

### 5. Struct/Record and Enum Processing Duplicated Between DWARF Modules

- Struct: `dwarf_metadata.py` `_process_struct` (L270-336) vs `dwarf_snapshot.py` `_process_record_type` (L516-585)
- Enum: `dwarf_metadata.py` `_process_enum` (L429-467) vs `dwarf_snapshot.py` `_process_enum` (L659-695)

Both follow the same ODR dedup pattern, same child iteration, same field extraction. The data models differ slightly (`FieldInfo` vs `TypeField`), so consolidation requires a shared extraction function that returns a common intermediate representation.

### 6. Qualifier Unwrapping Duplicated Within dwarf_advanced.py

- `_unwrap_qualifiers` (L395-424) — standalone function with depth limit 12 and caching
- `_get_type_align` (L217-232) — inline loop with depth limit 4 doing the same unwrapping

**Fix:** `_get_type_align` should call `_unwrap_qualifiers` instead of reimplementing the loop.

### 7. Inline Reference Resolution Ignores Existing Utility

`dwarf_advanced.py` reimplements `dwarf_utils.resolve_die_ref` logic inline at lines 210-213 and 523-526, despite the utility being available.

**Fix:** Replace inline code with calls to `dwarf_utils.resolve_die_ref`.

### 8. Forward-Ref/Anonymous Filtering Repeated 3 Times in pdb_metadata.py

Lines 123-129, 198-202, and 243-246 all repeat the same guard pattern.

**Fix:** Extract `_is_user_visible(name, is_forward_ref)` predicate.

### 9. Redundant Double Iteration Over all_structs() in pdb_metadata.py

`_extract_struct_layouts` (L122) and `_extract_calling_conventions` (L243) both iterate all structs. The second pass could be folded into the first.

### 10. PE Open/Parse/Close Ceremony Duplicated

`pdb_utils.py` (L182-240) and `pe_metadata.py` (L126-201) both open/parse/close PE files independently. When processing a DLL, the same PE is parsed twice from disk.

### 11. Loadability Logic Duplicated Inline in stack_checker.py

**Confidence: CONFIRMED.** `check_single_env()` (L207-214) reimplements the exact same if/elif cascade as `_compute_loadability()` (L70-82) in the same file.

**Fix:** Replace lines 207-214 with `loadability = _compute_loadability(graph, missing, version_mismatches)`. Drop-in replacement.

### 12. Missing-Symbol/Version-Mismatch Collection Duplicated in appcompat.py

`check_appcompat()` (L521-536) and `check_against()` (L600-614) share ~20 lines of nearly verbatim symbol/version checking logic within the same file.

### 13. Forward-Ref Resolution Uses 4 Passes in pdb_parser.py

`pdb_parser.py` L661-673: iterates structs twice and enums twice. Can be done in 2 passes.

---

## Low Severity

### 14. DIE Traversal Pattern — 3 Implementations (Intentional Differences)

**Reclassified from High to Low after review.**

The three DIE walkers have **intentionally different** skip-tag sets and subprogram handling:

| Module | `DW_TAG_subprogram` handling | Scope tracking |
|---|---|---|
| `dwarf_metadata.py` | Skips entirely (types only) | Full namespace chain |
| `dwarf_snapshot.py` | Processes at top level, no body descent | Full namespace chain |
| `dwarf_advanced.py` | Processes for calling convention, skips children | No scope tracking |

**Recommendation:** Do NOT consolidate into a shared `walk_dies()`. The differences are load-bearing. At most, share the skip-tag constants.

### 15. Skip/Prune Tag Sets Defined 3 Times

The base set `{DW_TAG_inlined_subroutine, DW_TAG_lexical_block, DW_TAG_GNU_call_site}` is common. Each module adds module-specific entries.

**Fix:** Define `_BASE_PRUNE_TAGS` in `dwarf_utils.py`; modules compose with their additions.

### 16. ELF Open/DWARF Check Boilerplate Appears 4 Times

`dwarf_unified.py` was created as an I/O optimization wrapper (NOT a replacement). The old modules are the actual implementations it delegates to. The boilerplate is somewhat unavoidable given the architecture.

### 17. DiffResult Property Recomputation

**Reclassified from Medium to Low after review.**

The `_effective_kind_sets()` computation is cheap (simple frozenset construction with early exit). The O(N) list scans are the real cost, but with typical change counts in the hundreds and at most 4-8 accesses per report, the practical impact is negligible. Additionally, `DiffResult` is mutated post-construction in `cli.py` (line 1092: `--show-redundant` path), making `@cached_property` fragile.

**Recommendation:** If addressed, use a single-pass partition method rather than caching. Low priority.

### 18. Graph-to-Dict Serialization — Partial Overlap

**Corrected from original analysis.** The per-node and per-edge dicts are identical between `stack_report.py` and `cli.py`, but the top-level structures differ (`stack_report` includes `root`/`node_count`; `cli.py` uses a `DependencyInfo` dataclass with `bindings_summary`/`missing_symbols`).

**Fix:** Extract shared `_node_to_dict()`/`_edge_to_dict()` helpers. Modest value.

### 19. Typedef-to-Anonymous-Type Resolution Duplicated

`dwarf_metadata.py` `_process_typedef` (L238-263) and `dwarf_snapshot.py` `_process_typedef` (L701-737) — nearly identical logic.

### 20. `_parse_struct` / `_parse_union` Near-Identical in pdb_parser.py

Lines 703-720 and 722-738 differ only in format string and `is_union` flag.

### 21. PdbFileName Extraction Repeated Verbatim in pdb_utils.py

Lines 221-226 and 229-232 contain identical 5-line blocks.

### 22. Machine Type Constants Defined in Two Places

`pdb_metadata.py` L56-63 defines `_MACHINE_NAMES`; `pe_metadata.py` L140-142 uses `pefile.MACHINE_TYPE`.

### 23. Element-Kind Classification Logic in 3 Places

`reporter.py` `ShowOnlyFilter.matches()`, `html_report.py`, and `report_classifications.py` each have independent prefix-to-category mappings.

### 24. `_VERDICT_LABEL` Dict is Redundant

`reporter.py` L36-50: `_VERDICT_LABEL` is redundant since `Verdict` is a `str` Enum where `.value` gives the label.

### 25. Bindings Summary Counting Duplicated

`stack_report.py` (L213-219) and `cli.py` (L407-409) count bindings by status identically.

### 26. Adjacency-List Construction Duplicated

`binder.py` (L142-146) and `stack_report.py` (L235-240) both build adjacency lists from `graph.edges`.

### 27. `_find_resolved_key` Linear Scan in resolver.py

**Reclassified from Medium to Low.** The O(V) scan is technically correct but `graph.nodes` is typically small (tens to low hundreds). The I/O cost of `parse_elf_metadata()` dominates. Trivially fixable with a `soname_to_key` dict but practically insignificant.

### 28. Private `_bitfields` Access from Outside pdb_parser.py

`pdb_metadata.py` L171 accesses `types._bitfields.get(member.type_ti)` directly. A public `get_bitfield(ti)` method should be added.

---

## Estimated Impact of Fixes

| Priority | Issues | Est. Lines Saved | Risk | Effort |
|----------|--------|------------------|------|--------|
| High | #1-4 | ~390 lines | Low | Medium |
| Medium | #5-13 | ~150 lines | Medium | Medium |
| Low | #14-28 | ~80 lines | Low | Low |
| **Total** | **28** | **~620 lines** | | |

### Key Review Corrections Applied
1. **DIE traversal (#14)**: Downgraded High→Low. The 3 implementations have intentionally different skip-tag sets and subprogram handling. Do NOT consolidate.
2. **DiffResult recomputation (#17)**: Downgraded Medium→Low. Computation is cheap; mutation hazard makes caching fragile.
3. **Graph-to-dict (#18)**: Corrected to partial overlap — top-level structures differ.
4. **Binary format detection (#3)**: Noted that implementations differ in Mach-O magic coverage; consolidation should use the most complete version.
5. **`_CHANGED_BREAKING_KINDS`**: Confirmed as dead code in `html_report.py`.
