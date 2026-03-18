# Implementation Plan: Fix All 7 Confirmed Bugs

*Updated after critical review — 4 of 7 plans revised.*

## Bug 1: Duplicate Enum Change Detection

### Root Cause
The `_DWARF_TO_AST_EQUIV` map at checker.py:1772 has struct entries but zero enum
entries. However, simply adding enum entries won't work because:
- AST detector uses symbol=`"Color"` (enum type name)
- DWARF detector uses symbol=`"Color::GREEN"` (qualified member name)
- The cross-kind dedup matches by exact symbol, so these will never match

### Fix Strategy (REVISED)
~~Same-kind dedup pass~~ — **rejected** due to false-positive risk (AST finding
for `Color` could cover different members than DWARF finding for `Color::GREEN`).

**New approach: Fix at the source.** Make AST's `_diff_enums()` use member-qualified
symbols (`"Color::GREEN"` instead of `"Color"`), matching the DWARF convention.
Then the existing exact dedup by `(kind, description)` handles it automatically.

Specifically, in checker.py `_diff_enums()`:
1. Change `symbol=name` → `symbol=f"{name}::{mname}"` for member-level findings
2. The existing `_deduplicate_ast_dwarf()` will now match by exact symbol+description

### Architectural Note
This is a localized fix. No schema/design changes needed.

---

## Bug 2: Raw Python Repr in func_params_changed

### Root Cause
checker.py:218-219 calls `str()` on a list of `(type, ParamKind)` tuples. Python
renders enum objects inside containers with their full repr.

### Fix Strategy
Format parameters as human-readable strings: `"int, int"` instead of
`"[('int', <ParamKind.VALUE: 'value'>), ...]"`.

Create a small helper `_format_params()` that joins `p.type` values with `, `,
appending kind qualifiers only when non-VALUE (e.g., `int*, const int&`).

### Architectural Note
Localized fix, no design changes needed.

---

## Bug 3: Snapshot Shows JSON File Metadata

### Root Cause
- `_collect_metadata()` is called on the input path (the .json file)
- AbiSnapshot has no field to store source file metadata
- Serialization doesn't save/restore it

### Fix Strategy (SIMPLIFIED)
~~Schema v3→v4 bump~~ — **unnecessary**. Simpler approach:

When `_collect_metadata()` receives a `.json` input, detect it's a snapshot and
skip metadata collection (or pull `library` name from the loaded snapshot).
No schema change required — just fix the CLI wiring.

Specifically:
1. In `_resolve_input()` or `_collect_metadata()`, check if input is a `.json` file
2. If so, skip computing sha256/size (they're for the JSON file, not the binary)
3. Use the `library` field from the loaded snapshot for display
4. Return `None` metadata or a sentinel indicating "loaded from snapshot"

### Architectural Note
Localized fix. No schema change needed. Backward compatible by definition.

---

## Bug 4: Policy Overrides Don't Affect Report Sections

### Root Cause
checker.py:2273 stores only `policy_file.base_policy` in `DiffResult.policy`.
All downstream code (DiffResult properties, reporter, report_summary) re-classifies
changes using `_policy_kind_sets(policy_name)` which only knows 3 built-in policies
and ignores any overrides.

### Fix Strategy (REVISED)
~~Store 4 pre-computed frozensets~~ — **rejected** because overrides are
`ChangeKind → Verdict` enums, not severity strings. Pre-computed sets become stale.

**New approach: Store the PolicyFile on DiffResult.**
1. Add `policy_file: PolicyFile | None = None` field to DiffResult
2. Add `_effective_kind_sets()` method that starts from the base policy's sets
   and applies overrides (moving kinds between breaking/source/risk/compatible)
3. Modify DiffResult properties (.breaking, .source_breaks, .risk, .compatible)
   to call `_effective_kind_sets()` when `policy_file` is set
4. Reporter already uses DiffResult properties, so it gets correct values automatically

### Architectural Note
This is the most impactful change. It affects the DiffResult contract but is
backward-compatible (None means "use policy name lookup" as before).

---

## Bug 5: Unhandled FileNotFoundError

### Root Cause
cli.py:1103 (and 7 other locations) calls `output.write_text()` without ensuring
parent directory exists.

### Fix Strategy (EXPANDED)
Found **8 write_text() calls** (not 4 as originally identified). All need the helper.
The `output_dir.mkdir(parents=True, exist_ok=True)` at line 1375 is the existing
precedent in `batch_cmd`.

Add a helper `_safe_write_output(output: Path, text: str)` that:
1. Creates parent dir: `output.parent.mkdir(parents=True, exist_ok=True)`
2. Wraps in try/except for clear error message via `click.ClickException`
3. Replace all 8 write_text() call sites

### Architectural Note
Localized fix. Follows existing batch_cmd precedent.

---

## Bug 7: deps Reports PASS for Non-ELF Files

### Root Cause
`parse_elf_metadata()` returns empty ElfMetadata on failure. The resolver adds
a node with empty deps. stack_checker sees 1 node, 0 issues → PASS.

### Fix Strategy (CONFIRMED)
Validate ELF magic bytes at CLI level using the existing `_detect_binary_format()`
helper (already used by `compare_cmd` and `dump_cmd`).

Add validation to both `deps_cmd` and `stack_check_cmd`:
```python
fmt = _detect_binary_format(binary)
if fmt != "elf":
    raise click.ClickException(
        f"deps requires an ELF binary; got {fmt or 'unknown format'}: {binary}"
    )
```

### Architectural Note
Localized fix. Uses existing `_detect_binary_format()` helper — no new code needed
for detection.

---

## Bug 8: affected_pct Always 0.0

### Root Cause
`build_summary()` at report_summary.py:71 calls `compatibility_metrics()` without
`old_symbol_count`. The count is available in the old snapshot but not threaded
through.

### Fix Strategy (REVISED)
~~Add parameter to build_summary()~~ — **rejected** because reporter call sites
only have DiffResult (no access to old snapshot to compute the count).

**New approach: Store `old_symbol_count` on DiffResult.**
1. Add `old_symbol_count: int | None = None` to DiffResult dataclass (checker.py)
2. Compute it once in `compare()` function after creating DiffResult
3. `build_summary()` reads `result.old_symbol_count` directly
4. Eliminate duplicate computation in cli.py, compat/cli.py, html_report.py

### Architectural Note
Small DiffResult extension. Computed once at source (`compare()`), available
everywhere. Eliminates 3 duplicate computation sites.
