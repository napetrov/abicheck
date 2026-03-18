# Implementation Plan: Fix All 7 Confirmed Bugs

## Bug 1: Duplicate Enum Change Detection

### Root Cause
The `_DWARF_TO_AST_EQUIV` map at checker.py:1772 has struct entries but zero enum
entries. However, simply adding enum entries won't work because:
- AST detector uses symbol=`"Color"` (enum type name)
- DWARF detector uses symbol=`"Color::GREEN"` (qualified member name)
- The cross-kind dedup matches by exact symbol, so these will never match

### Fix Strategy
**Same-kind dedup pass** for enums: since both detectors emit the *same* ChangeKind
(`ENUM_MEMBER_VALUE_CHANGED`), add a dedup pass that recognizes when an AST enum
change for type `X` and a DWARF enum change for `X::member` describe the same thing.

Specifically, in `_deduplicate_ast_dwarf()`:
1. Build an index of AST enum findings: `{(kind, enum_name): Change}`
2. For each DWARF enum finding where symbol contains `::`, extract the enum name
3. If an AST finding exists for the same (kind, enum_name), drop the DWARF one

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

### Fix Strategy
1. Add `source_metadata` field to AbiSnapshot model (path, sha256, size_bytes)
2. Populate it during `dump` command from the original binary
3. Serialize/deserialize it (schema v4)
4. In `compare` CLI, when input is a snapshot, extract metadata from the loaded
   snapshot instead of computing it from the .json file

### Architectural Note
**Schema version bump v3 → v4.** Backward compatible: old snapshots without
`source_metadata` will show `—` in reports (same as today for missing metadata).

---

## Bug 4: Policy Overrides Don't Affect Report Sections

### Root Cause
checker.py:2273 stores only `policy_file.base_policy` in `DiffResult.policy`.
All downstream code (DiffResult properties, reporter, report_summary) re-classifies
changes using `_policy_kind_sets(policy_name)` which only knows 3 built-in policies
and ignores any overrides.

### Fix Strategy
Store the **effective kind-sets** in DiffResult, not just the policy name:
1. Add `policy_kind_sets: tuple[frozenset, frozenset, frozenset, frozenset] | None`
   field to DiffResult
2. When PolicyFile is used, compute the effective kind-sets by applying overrides
   to the base policy's sets, and store them
3. Modify DiffResult properties (.breaking, .source_breaks, .risk, .compatible)
   to use stored kind-sets when available, falling back to name-based lookup
4. Reporter already uses DiffResult properties, so it gets correct values automatically

### Architectural Note
This is the most impactful change. It affects the DiffResult contract but is
backward-compatible (None means "use policy name lookup" as before).

---

## Bug 5: Unhandled FileNotFoundError

### Root Cause
cli.py:1103 (and 3 other locations) calls `output.write_text()` without ensuring
parent directory exists.

### Fix Strategy
Add a helper `_safe_write_output(output: Path, text: str)` that:
1. Validates `output.parent` exists (or creates it)
2. Wraps in try/except for clear error message
3. Replace all 4 call sites

### Architectural Note
Localized fix.

---

## Bug 7: deps Reports PASS for Non-ELF Files

### Root Cause
`parse_elf_metadata()` returns empty ElfMetadata on failure. The resolver adds
a node with empty deps. stack_checker sees 1 node, 0 issues → PASS.

### Fix Strategy
In `_seed_root()` (resolver.py), after calling `parse_elf_metadata()`, check if
the result is essentially empty (no soname, no needed, no exports). If so, mark
the node as `elf_parse_failed=True`. Then in `check_single_env()`, if the root
node has `elf_parse_failed`, set loadability to FAIL.

Simpler alternative: validate ELF magic bytes at the CLI level in `deps_cmd`
before calling the stack checker.

### Architectural Note
The simpler CLI-level validation is preferred to avoid changing the resolver's
return contract.

---

## Bug 8: affected_pct Always 0.0

### Root Cause
`build_summary()` at report_summary.py:71 calls `compatibility_metrics()` without
`old_symbol_count`. The count is available in the old snapshot but not threaded
through.

### Fix Strategy
1. Add `old_symbol_count: int | None = None` parameter to `build_summary()`
2. Pass it through to `compatibility_metrics()`
3. At all call sites (reporter.py:195, 215, 382, 452), compute the count from
   `result` when available and pass it
4. html_report.py already does this correctly — use the same pattern

### Architectural Note
Localized fix. The old_symbol_count should ideally live on DiffResult directly
to avoid computing it at every call site, but adding a parameter to build_summary
is sufficient and less invasive.
