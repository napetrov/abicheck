# Performance Optimization Spec — Implementation Requirements

**Status:** Spec (replaces commit `1573dcf`)
**Source:** `docs/performance-analysis.md` gaps 1–5, reviewed by 4 domain reviewers

This document specifies the exact changes to make, what to avoid, and which
tests must accompany each change. Changes are grouped by verdict: **merge
as-is**, **merge with fixes**, **rework**, and **revert**.

---

## Fix 1 — REWORK: `_enrich_affected_symbols` reverse index (`checker.py`)

### Problem

The ancestor-lookup loop in `_enrich_affected_symbols` re-scans all public
functions for every `(affected_type, ancestor)` pair. For large libraries this
is O(T × A × F × P).

### What the previous attempt got wrong

1. **Misleading comment** — claimed O(1) reverse-index lookups, but the primary
   loop `for mangled, func in old_pub` × `for tname in affected_types` ×
   `any(tname in ft …)` is still O(F × T × P), unchanged.
2. **Redundant data structure** — `func_type_index` duplicates information
   already in `type_to_funcs` / `type_to_mangled` and is only consumed to seed
   `all_type_func_index`.
3. **Subtle behavioral change** — added `and type_to_funcs[parent]` truthiness
   check on the `if parent in type_to_funcs` branch, causing empty-list parents
   to fall through to the `elif`/`else` branches. This can surface different
   results for edge cases where an affected type is also an ancestor of another
   affected type but has no matching functions.
4. **`set` → `list`** for `func_type_strs` — lost deduplication of identical
   type strings (e.g., `int foo(int x)`). Functionally equivalent but
   marginally slower.

### Required implementation

**Option A — true reverse index (preferred if F × T × P is the bottleneck):**

```
# One pass: build  type_substr → set[(func_name, mangled)]
# Key: every unique type string from all public function signatures
# Then for each affected type, check which keys contain it as substring
reverse_index: dict[str, set[tuple[str, str]]] = defaultdict(set)
for mangled, func in old_pub.items():
    type_strs = set()
    if func.return_type:
        type_strs.add(func.return_type)
    for p in func.params:
        if p.type:
            type_strs.add(p.type)
    for ts in type_strs:
        reverse_index[ts].add((func.name, mangled))

for tname in affected_types:
    for ts, funcs in reverse_index.items():
        if tname in ts:
            for fname, mname in funcs:
                type_to_funcs[tname].append(fname)
                type_to_mangled[tname].append(mname)
```

This is O(F × P) for index build + O(T × U) for lookups (U = unique type
strings), which is typically ≪ F × T × P.

**Option B — keep original loop, add only ancestor caching:**

Keep the original primary loop verbatim (`set` for `func_types_used`, original
variable names). Only add caching for the ancestor-lookup loop:

```python
# Cache: scanned ancestors → list of (func_name, mangled)
_ancestor_func_cache: dict[str, list[tuple[str, str]]] = {}

for tname in affected_types:
    ancestors = _all_ancestors(tname)
    for parent in ancestors:
        if parent in type_to_funcs:  # <-- NO truthiness check, keep original
            type_to_funcs[tname].extend(type_to_funcs[parent])
            type_to_mangled[tname].extend(type_to_mangled.get(parent, []))
        elif parent in _ancestor_func_cache:
            for fname, mname in _ancestor_func_cache[parent]:
                type_to_funcs[tname].append(fname)
                type_to_mangled[tname].append(mname)
        else:
            parent_funcs: list[tuple[str, str]] = []
            for _m, func in old_pub.items():
                func_types_used = {func.return_type} | {p.type for p in func.params}
                if any(parent in ft for ft in func_types_used if ft):
                    parent_funcs.append((func.name, _m))
            _ancestor_func_cache[parent] = parent_funcs
            for fname, mname in parent_funcs:
                type_to_funcs[tname].append(fname)
                type_to_mangled[tname].append(mname)
```

### Constraints

- Do NOT change the `if parent in type_to_funcs:` condition — keep original
  semantics (no added truthiness check).
- Keep `set[str]` for `func_types_used` — do not change to `list`.
- Remove `func_type_index` — it is redundant.
- Update the comment to accurately describe the actual complexity reduction.

### Required tests

1. **Ancestor with empty function list** — an affected type whose parent is also
   in `affected_types` but has an empty function list. Assert same output before
   and after optimization.
2. **Shared ancestors** — two affected types sharing the same ancestor chain.
   Assert ancestor functions scanned only once (mock `old_pub` and count calls).
3. **Type appearing in both return and param** — `int foo(int x)` style, verify
   deduplication still works.

---

## Fix 2 — MERGE: Pre-compiled regex in `_match_root_type` (`checker.py`)

### Summary

Pre-compile word-boundary regex patterns for all root type names once in
`_filter_redundant`, pass the dict to `_match_root_type`. This is the most
impactful optimization in the PR.

### Implementation (already correct, merge with nits)

Lines 2239–2244 (pattern dict), 2314–2338 (`_match_root_type` signature).

### Nits to fix before merge

1. **Line 2333**: change `if compiled_patterns and type_name in compiled_patterns`
   to `if compiled_patterns is not None and type_name in compiled_patterns`.
   An empty dict `{}` is falsy and would incorrectly skip the cache.

### Required tests

1. **`_match_root_type` with `compiled_patterns=None`** — verify fallback
   recompilation still works (backward compatibility).
2. **`_match_root_type` with pre-compiled dict** — verify same results as
   without.
3. **Empty `compiled_patterns` dict** — verify it doesn't incorrectly skip
   the cache (regression test for the truthiness nit).

---

## Fix 3 — MERGE: Regex caching in `_is_pointer_only_type` / `_has_public_pointer_factory` (`checker.py`)

### Summary

Pass shared `dict[str, re.Pattern]` caches to opaque-type checking functions
so that patterns are compiled once per type across all calls from
`_filter_opaque_size_changes`.

### Implementation (already correct, merge as-is)

Lines 2358–2371 (`_is_pointer_only_type`), 2411–2420
(`_has_public_pointer_factory`), 2472–2495 (call sites with shared caches).

### No changes needed

The cache-via-parameter pattern is acceptable for `_`-prefixed internal helpers.

### Required tests

1. **Shared cache correctness** — call `_is_pointer_only_type` for two
   different type names with the same cache dict. Verify both results are
   correct and the cache dict contains both entries.
2. **`_re_cache=None` fallback** — verify function works without cache.

---

## Fix 4 — REVERT: DWARF `reversed(list(...))` replacement

### Files

- `abicheck/dwarf_advanced.py:276–279`
- `abicheck/dwarf_metadata.py:230–234`
- `abicheck/dwarf_snapshot.py:295–298`

### Why revert

1. `reversed()` on a list does **not** create a copy — it returns a lazy
   `list_reverseiterator`. The comment "Iterate children in reverse without
   creating a reversed copy" is factually wrong.
2. The manual `range(len(children) - 1, -1, -1)` loop is less readable
   than `reversed(children)` with no measurable performance benefit.
3. All three files had the same incorrect "optimization" applied.

### Required action

Restore original code in all three files:

```python
# dwarf_advanced.py
stack.extend(reversed(list(die.iter_children())))

# dwarf_metadata.py
for child in reversed(list(die.iter_children())):
    stack.append((child, next_scope))

# dwarf_snapshot.py
for child in reversed(list(die.iter_children())):
    stack.append((child, next_scope))
```

No new tests needed — this is a pure revert.

---

## Fix 5 — MERGE with fixes: ELF section pre-capture (`elf_metadata.py`)

### Summary

Capture `.gnu.version` and `.dynsym` sections during the main
`iter_sections()` loop and pass them to `_correlate_symbol_versions_fast`,
avoiding redundant re-iteration.

### Implementation (mostly correct, fix nits)

Lines 200–204 (section variables), 213–218 (capture in loop), 226–230 (call
site), 496–530 (new function).

### Required fixes

1. **Restore docstring content** — the original `_correlate_symbol_versions`
   docstring explained the `.gnu.version` section format (index semantics,
   VER_NDX_LOCAL, VER_NDX_GLOBAL, bit 15). The new `_correlate_symbol_versions_fast`
   replaced this with a one-liner. Restore the full docstring — it documents
   the ELF format, not the implementation.

2. **Drop `_fast` suffix** — since the old function is deleted, there is no
   ambiguity. Name it `_correlate_symbol_versions` (same as original) to avoid
   gratuitous rename churn. Update the call site accordingly.

3. **Remove the `GNUVerSymSection` import added at line 39** — the original
   code imported it inside the function body. Since the function no longer needs
   the local import (the section is passed as a parameter), verify whether the
   top-level import is needed by type annotations. If the parameter type is
   `GNUVerSymSection | None`, the import is correct and should stay. If not
   used in annotations, remove it and keep it as a local import or use
   `TYPE_CHECKING`.

### Required tests

1. **Missing `.gnu.version` section** — ELF without `.gnu.version`. Verify
   `ver_sym_section` is `None` and function returns early gracefully.
2. **Missing `.dynsym` section** — ELF without `.dynsym`. Verify
   `dynsym_section` is `None` and function returns early.
3. **Normal ELF** — verify identical output to the old implementation.

---

## Implementation Order

1. **Fix 4** (revert DWARF changes) — trivial, no dependencies
2. **Fix 5** (ELF section pre-capture with nits) — self-contained
3. **Fix 2** (regex pre-compilation in `_match_root_type`) — self-contained
4. **Fix 3** (regex caching in opaque-type checks) — self-contained
5. **Fix 1** (`_enrich_affected_symbols` rework) — most complex, do last

Each fix should be a **separate commit** with its own tests.

---

## Process Requirements

- Each fix must have tests **before** the implementation (TDD) or in the same
  commit.
- All 3464 existing tests must continue to pass after each commit.
- Run `python -m pytest tests/ -x -q` after each commit to verify.
- Comments must accurately describe the actual algorithmic improvement, not
  overstate it.
