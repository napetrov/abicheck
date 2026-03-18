# Peer Review Notes on FIX_SPEC.md

**Date:** 2026-03-18
**Reviewers:** 4 independent review agents (architecture-focused)
**Document reviewed:** FIX_SPEC.md (9 fix proposals)

---

## Executive Summary

The fix specification is thorough and well-researched. Reviewers identified
**12 actionable improvements**, **6 missing test cases**, and **3 design
corrections** that should be incorporated before implementation begins.

No fix proposal was rejected outright — all are directionally correct. The
most significant feedback is on **FIX-B** (recommended architecture inversion)
and **FIX-C** (scope limiting needed).

---

## FIX-A Review: Header C++ Mangling

### Concern 1: Heuristic fragility (Part 1)

The `_detect_header_language()` heuristic scans file contents for C++ keywords
like `class `, `namespace `, `template<`. This will **false-positive** on:
- C headers with C++ keywords in comments: `/* This class of errors... */`
- C headers with `#ifdef __cplusplus` guards (very common for C/C++ compat)
- C headers that `#include` C++ headers transitively

**Recommendation:** The heuristic is a useful optimization but should NOT be
the primary fix. Part 2 (extern "C" fallback matching) is the robust fix and
should work independently of the heuristic. The heuristic can be a "nice to
have" that avoids unnecessary C++ mangling when clearly not needed.

### Concern 2: Extern "C" name collision risk (Part 2)

The fallback `old_by_name` dict (`{f.name: f for f in old_map.values() if
f.is_extern_c}`) creates a dict keyed by **plain name**. If two extern "C"
functions have the same plain name in different translation units (unlikely
but possible with weak symbols or version scripts), the dict silently drops
one. This is low risk but should be documented.

### Concern 3: Appcompat dual-mismatch (Part 3) — Store both forms

The spec's "alternative approach" of storing both `func.name` (demangled) and
`func.mangled` in `affected_symbols` is **better than the demangling approach**
for the `affected_symbols` mismatch (Mismatch 2). It avoids the demangling
dependency for this specific case. The demangling approach is still needed for
Mismatch 1 (`change.symbol` matching).

**Accepted recommendation:** Use the hybrid approach:
- Store `func.mangled` in a parallel `affected_mangled_symbols` field
- Match against `app.undefined_symbols` using mangled set
- Display using demangled set in reports

---

## FIX-B Review: C++ DWARF Function Extraction

### MAJOR: Invert the architecture — DW_AT_external as primary gate

The most significant review finding. The spec recommends "Option A (demangled
index) with Option C (DW_AT_external) as a fast supplement." Reviewer argues
this should be **inverted**:

**Recommended approach: Option C as primary, Option A as validation:**

1. Accept DWARF subprograms where `DW_AT_external=true` AND (`DW_AT_low_pc`
   exists OR `DW_AT_ranges` exists). This filters declarations and
   inline-only functions.
2. Use the demangled ELF index as a post-hoc filter/validation to remove
   false positives (LTO-eliminated, hidden-visibility functions).

**Rationale:**
- `DW_AT_external` is the DWARF standard's definition of "visible outside
  compilation unit" — exactly what abicheck needs
- The current code already reads `DW_AT_external` at line 408 (sets `is_static`)
- This approach doesn't depend on demangling correctness at all for the
  common case
- The `DW_AT_low_pc` check prevents inline-only functions from leaking in

**Accepted with modification:** Implement the inverted architecture. The
demangled index becomes a refinement layer, not the primary mechanism.

### Concern 2: cxxfilt is NOT pure Python

The spec incorrectly states cxxfilt is "pure Python, lightweight." It is
actually a ctypes wrapper around `libstdc++`'s `__cxa_demangle`. It requires
`libstdc++.so` at runtime, which may be absent on Alpine/musl or minimal
containers.

**Accepted:** Update spec to accurately document the dependency chain.

### Concern 3: Subprocess fallback performance

Per-symbol `subprocess.run(["c++filt", symbol])` is ~5ms per call. For a
library with 5000 symbols, that's 25 seconds. The `lru_cache` doesn't help
for initial index building (each symbol is unique).

**Accepted recommendation:** Use batched demangling:
```python
proc = subprocess.run(
    ["c++filt"], input="\n".join(symbols),
    capture_output=True, text=True, timeout=30
)
```

This reduces N subprocess calls to 1.

### Concern 4: Missing warning on demangling unavailability

If both cxxfilt and c++filt are unavailable, the tool silently degrades to
the original buggy behavior (0 functions). A warning should be logged.

**Accepted:** Add `_log.warning("C++ demangling unavailable; DWARF export
matching may be incomplete")` when all demangling backends fail.

### Concern 5: Remove dead code

The "Name-in-demangled" block (lines 286-290 of proposed code) with `pass`
and a comment explaining why it doesn't work is noise. Remove it.

**Accepted.**

### Missing test cases for FIX-B

Reviewer identified 6 gaps:
1. **Template functions** (e.g., `std::vector<int>::push_back`)
2. **Operator overloads** (`operator<<`, `operator==`)
3. **D0/D1/D2 virtual destructor variants**
4. **Missing DW_AT_linkage_name entirely** (most common real trigger)
5. **Namespace-scoped free functions** (`ns::foo()`)
6. **Graceful degradation** when no demangler is available

**All accepted** — add to test plan.

---

## FIX-C Review: Enum Change Deduplication

### IMPORTANT: Scope the dedup to enum kinds only

The proposed `(kind, symbol)` dedup pass is applied globally to all change
kinds. This risks incorrectly merging legitimately different changes that
share the same kind+symbol (e.g., two different field-level changes on the
same type). The fix should be **scoped to enum ChangeKinds only**:

```python
_ENUM_DEDUP_KINDS = frozenset({
    ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
    ChangeKind.ENUM_MEMBER_REMOVED,
    ChangeKind.ENUM_LAST_MEMBER_VALUE_CHANGED,
})
```

Only apply the same-kind symbol dedup for these specific kinds.

**Accepted.**

### Concern 2: Replace "longer description" heuristic

String length as a quality proxy is fragile. Better: **prefer the change with
populated `old_value`/`new_value` fields**, or use a deterministic source
preference ("prefer DWARF-sourced changes for enums").

**Accepted:** Use `old_value`/`new_value` population as the tiebreaker instead
of description length.

### Concern 3: Remove "Change 1" (inapplicable approach)

The spec lists "Change 1: Add enum kinds to `_DWARF_TO_AST_EQUIV`" and then
immediately explains why it doesn't work. This is confusing. Remove it or
relabel as "Considered and Rejected."

**Accepted.**

### Concern 4: Fix the O(n) `stage2.remove()`

Replace with a two-pass approach:
```python
best: dict[tuple[str, str], Change] = {}
for c in stage1:
    key = (c.kind.value, c.symbol)
    if key not in best or _is_better(c, best[key]):
        best[key] = c
stage2 = [c for c in stage1 if best.get((c.kind.value, c.symbol)) is c]
```

**Accepted.**

### Missing test cases for FIX-C

1. `ENUM_LAST_MEMBER_VALUE_CHANGED` dedup (sentinel members)
2. `ENUM_MEMBER_REMOVED` — verify existing exact dedup covers it (lock-in test)
3. Input order independence (DWARF change first vs AST change first)

**All accepted.**

---

## FIX-D Review: Compiler Internal Types

### Concern: `__` prefix rule may be too aggressive

Types starting with `__` are reserved by the C/C++ standard, but appear in
practice in embedded/kernel code (e.g., `__attribute_packed_struct`).

**Recommendation:** Use **only the explicit `frozenset`** of known compiler
internals instead of the blanket `__` prefix. The castxml path uses the prefix
rule for consistency with existing behavior, but the DWARF path should be more
conservative since it's a new filter. If the explicit list grows unwieldy,
add the prefix rule later with an escape hatch.

**Partially accepted:** Keep the explicit frozenset as the primary mechanism.
Add the `__` prefix as a secondary check that can be disabled. For v1, the
explicit frozenset alone is sufficient and safer.

---

## FIX-E Review: Stripped Binary Policy

### Concern: Threading --strict-elf-only through compare()

The spec shows the flag in `cli.py` and `_check_removed_function()` but doesn't
show how it gets from CLI → `compare()` → detector. The current `compare()`
signature has no `strict_elf_only` parameter.

**Recommended approach:** Implement as a synthetic `PolicyFile` override
constructed at the CLI layer when the flag is set. This avoids threading a
new parameter through the entire call chain and reuses existing architecture:

```python
if strict_elf_only:
    override = PolicyFile(overrides={ChangeKind.FUNC_REMOVED_ELF_ONLY: Verdict.BREAKING})
    policy_file = PolicyFile.merge(policy_file, override) if policy_file else override
```

**Accepted.** Also move FIX-E from Phase 3 to Phase 1 (it's trivial and has
no dependencies).

---

## FIX-F Review: Struct Offset Dedup

### Concern: Description-based field matching is fragile

The proposed fix parses description strings to verify field names match. This
is brittle because description format is not part of the contract.

**Simpler alternative (accepted):** Change the DWARF detector to emit
`symbol="Point"` (the type name) instead of `symbol="Point::x"` for
`STRUCT_FIELD_OFFSET_CHANGED`, since the field name is already in the
description. This makes both sides use the same symbol key naturally, and
the existing cross-kind dedup works without modification.

If changing emission is too risky (could affect suppression rules that match
`"Point::x"`), use the parent-extraction approach but match against the `ast_findings`
**set of symbols**, not against descriptions.

### Test gap: Nested types

Add test for `Outer::Inner::field` where `rsplit("::", 1)` produces
`parent="Outer::Inner"`.

**Accepted.**

---

## FIX-G Review: JSON Per-Change Severity

### Concern 1: Add `"policy"` key to JSON

Without recording which policy was used, the severity values are
uninterpretable. Add a top-level `"policy": "strict_abi"` key to the JSON
output.

**Accepted.**

### Concern 2: Handle leaf-mode change dicts

The leaf-mode JSON (`to_leaf_json`) builds type change dicts inline (lines
401-410 of reporter.py) without calling `_change_to_dict`. The severity field
will be inconsistent between `leaf_changes` and `non_type_changes` entries.

**Accepted:** Ensure both paths produce severity field.

### Concern 3: Make `_policy_kind_sets` public

The spec references `policy_kind_sets()` but the actual function is
`_policy_kind_sets()` (private). Either make it public or add a wrapper.

**Accepted.**

---

## FIX-H Review: Leaf-Mode JSON Schema

### IMPORTANT: Schema heterogeneity risk

`leaf_changes` entries have different fields than `non_type_changes` entries
(e.g., leaf entries have `affected_count` but lack `old_value`/`new_value`).
Concatenating them into a single `"changes"` array produces a heterogeneous
list where consumers doing `change["old_value"]` on a leaf entry get KeyError.

**Accepted correction:** Normalize both entry types to a common schema before
merging. Use `_change_to_dict` for all entries, adding leaf-specific fields
as optional.

**Risk reassessment:** FIX-H risk upgraded from "None" to "Low" due to this
schema inconsistency concern.

---

## FIX-I Review: Duplicate Warnings

### Minor: Also fix variable dedup warning

The same pattern exists at `model.py:201-208` for variable indexing. Apply
the same `seen_dup_warning` throttle there.

**Accepted.**

---

## Shared `demangle.py` Module

### Concern 1: Batch subprocess fallback

Already covered in FIX-B review. Use batched `c++filt` invocation.

### Concern 2: `base_name()` parsing is fragile

Demangled names like `operator<<`, `operator()`, and templates with `::`
inside angle brackets will be parsed incorrectly. Document as best-effort
with known limitations, since it's only used for display (not matching).

**Accepted.**

### Concern 3: List as explicit Phase 2 item

The shared module is not listed in the implementation order table. It should
be an explicit Phase 2 prerequisite since both FIX-B and FIX-A depend on it.

**Accepted.**

---

## Implementation Order Corrections

| Change | Reason |
|--------|--------|
| Move FIX-E from Phase 3 → Phase 1 | Trivial, no dependencies |
| Add `demangle.py` as explicit Phase 2 item | FIX-B and FIX-A depend on it |
| FIX-C and FIX-F are independent | Despite both being in `_deduplicate_ast_dwarf` |

### Revised Order

| Phase | Fix | Complexity |
|-------|-----|-----------|
| 1 | FIX-D (compiler internals) | Small |
| 1 | FIX-I (duplicate warnings — functions + variables) | Small |
| 1 | FIX-C (enum dedup — scoped to enum kinds) | Small |
| 1 | FIX-E (strict-elf-only via PolicyFile override) | Small |
| 2 | `demangle.py` shared module (batch subprocess) | Small |
| 2 | FIX-B (C++ DWARF — DW_AT_external primary gate) | Medium |
| 2 | FIX-F (struct offset dedup) | Medium |
| 3 | FIX-A (header C mangling — 3-part fix) | Large |
| 4 | FIX-G (JSON severity + `"policy"` key) | Small |
| 4 | FIX-H (leaf JSON schema normalization) | Small |

---

## Complete Missing Test Cases Summary

Tests to add beyond those already in the spec:

### FIX-B additional tests
1. Template function extraction (`vector<int>::push_back`)
2. Operator overload extraction (`operator<<`, `operator==`)
3. D0/D1/D2 virtual destructor variant handling
4. Missing `DW_AT_linkage_name` entirely (no fallback to DW_AT_MIPS_*)
5. Namespace-scoped free functions (`ns::foo()`)
6. Graceful degradation without demangler (log warning, don't crash)
7. Explicit assert: no "no DWARF" warning for C++ compare-release

### FIX-C additional tests
8. `ENUM_LAST_MEMBER_VALUE_CHANGED` sentinel dedup
9. `ENUM_MEMBER_REMOVED` lock-in test (exact dedup already works)
10. Input order independence (DWARF first vs AST first)

### FIX-D additional test
11. User type starting with `__` behavior (document whether filtered)

### FIX-E additional test
12. `--strict-elf-only` + contradictory policy file precedence

### FIX-F additional test
13. Nested type `Outer::Inner::field` dedup

### FIX-G additional tests
14. `"unknown"` severity fallback case
15. Severity in leaf-mode change dicts

### FIX-H additional test
16. Schema consistency: all entries in `"changes"` have minimum required keys

### FIX-I additional test
17. Variable dedup warning throttle (`model.py:201-208`)
