# Architecture Review Fixes — Implementation Spec

> **Branch:** `claude/refactor-rules-architecture-AAkVz`
> **Status:** Partially implemented (commit `119587b3f`)
> **Scope:** 5 implemented fixes across 5 files, grouped into 2 problem areas
> **Out of scope:** FIX-C, FIX-E, FIX-G, FIX-H (implemented but documented
> separately). FIX-A Parts 2/3 (plain-name fallback in `diff_symbols.py`,
> demangled fallback in `appcompat.py`) are also out of scope for this spec.

### Terminology

| Term | Meaning |
|------|---------|
| **DWARF** | Debug information format embedded in ELF binaries |
| **DIE** | DWARF Information Entry — a single node in the DWARF tree |
| **ELF** | Executable and Linkable Format — the standard binary format on Linux |
| **AST** | Abstract Syntax Tree — parsed representation of C/C++ headers (via castxml) |
| **castxml** | Tool that parses C/C++ headers and emits an XML AST |

---

## Problem 1: Detection Accuracy

### FIX-A — C++ const-reference regex pattern in `dumper.py`

**File:** `abicheck/dumper.py` line 248

**Problem:**
The `_CPP_PATTERNS` list used `\bconst\s*&` to detect C++ const-reference
parameters and trigger C++ compilation mode. This regex matches the literal
text `const&` or `const &` but **never** matches real C++ code like
`const int&`, `const std::string&`, or `const MyClass&` because there is
always a type name between `const` and `&`.

**Root cause:** The regex allowed zero-or-more whitespace between `const` and
`&` but did not account for the mandatory type name token.

**Impact:** Headers containing only `const Type&` idioms (no other C++
indicators) would be misdetected as C and sent to castxml in C mode, producing
parse errors or missing symbols.

**Fix:**
```python
# Before (broken — matches only "const&" or "const &"):
re.compile(rb"\bconst\s*&")

# After (correct — matches "const int&", "const ns::Type &", etc.):
re.compile(rb"\bconst\s+\w[\w:]*\s*&")
```

**Regex breakdown:**
- `\bconst` — word boundary + `const` keyword
- `\s+` — one or more whitespace (mandatory gap before type name)
- `\w[\w:]*` — type name, allowing `::` for namespaced types (e.g. `std::string`)
- `\s*&` — optional whitespace + reference operator

**Known limitation:** The regex does not match `const TemplatedType<T>&`
because `<` is not in `[\w:]`. This is mitigated by other patterns in
`_CPP_PATTERNS` (template and namespace patterns) that catch templated code.

**Test coverage:** No dedicated test exercises the `\bconst\s+\w[\w:]*\s*&`
regex pattern in `_CPP_PATTERNS` directly. The `TestCanonicalizeTypeName`
class in `test_review_fixes.py` tests the *type-name canonicalization*
function (a separate C3 fix), not this regex.

---

### FIX-F — Parent-type dedup restricted to field-level change kinds

**File:** `abicheck/diff_filtering.py` lines 662–673

**Problem:**
In `_deduplicate_ast_dwarf()` Pass 3 (cross-kind dedup), the parent-type
matching logic checked if `"::" in c.symbol` for **all** DWARF change kinds.
This incorrectly suppressed DWARF findings for nested types like
`Outer::Inner` because `Inner` was treated as a "field" of `Outer`, and if
`Outer` had an AST finding, the `Inner` DWARF finding was dropped.

**Root cause:** The `::` separator is overloaded — it separates both
`Type::field` (field of struct) and `Outer::Inner` (nested type). The code
did not distinguish between these two cases.

**Impact:** Legitimate DWARF-only findings for nested types were silently
dropped during deduplication, causing missed ABI break reports.

**Fix:** Restrict parent-type dedup to field-level DWARF change kinds only:

```python
# Only these kinds represent "field of a struct" semantics:
_FIELD_LEVEL_KINDS = {
    ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
    ChangeKind.STRUCT_FIELD_REMOVED,
    ChangeKind.STRUCT_FIELD_TYPE_CHANGED,
}

# Before: if "::" in c.symbol:
# After:
if c.kind in _FIELD_LEVEL_KINDS and "::" in c.symbol:
    parent = c.symbol.rsplit("::", 1)[0]
    if any((ak.value, parent) in ast_findings for ak in equiv_ast_kinds):
        continue
```

**Why this works:** Type-level changes (STRUCT_SIZE_CHANGED,
STRUCT_ALIGNMENT_CHANGED) for `Outer::Inner` describe the nested type itself,
not a field of `Outer`. Only field-level changes (offset, removed, type
changed) should fall back to checking whether the parent type has an
equivalent AST finding.

**Note on `_FIELD_LEVEL_KINDS` duplication:** There are now two definitions
of `_FIELD_LEVEL_KINDS` in `diff_filtering.py`:
- Module-level (line 240): a `frozenset` with 17 field-level kinds including
  `TYPE_FIELD_*`, `STRUCT_FIELD_*`, `UNION_FIELD_*`, and others.
- Function-local inside `_deduplicate_ast_dwarf()` (line 665): a `set` with
  only 3 struct-specific kinds.

The function-local version intentionally restricts parent-type dedup to
struct field changes only (DWARF-specific kinds that have AST equivalents).
Union field changes with `::` in the symbol name (e.g. `MyUnion::member`)
will bypass parent-type dedup, which may cause duplicate reports in rare cases.

**Test coverage:** No test in `test_review_fixes.py` constructs a scenario
with nested types (e.g. `Outer::Inner`) to verify that
`_deduplicate_ast_dwarf` preserves them. This path is exercised indirectly
through `compare()` integration tests but without targeted assertions.

---

## Problem 2: Code Hygiene & Deduplication

### FIX-B1 — Dead parameter removal in `dwarf_snapshot.py`

**File:** `abicheck/dwarf_snapshot.py` — `_is_exported()` method (line 735)
and call sites (lines 319, 426)

**Problem:**
The `_is_exported()` method accepted a keyword argument
`is_dwarf_external: bool = False` that was extracted from
`DW_AT_external` at the call site but **never used** inside the method body.
The three-tier matching logic (exact mangled → plain name → demangled fallback)
operated entirely on the ELF symbol table and did not consult this flag.

**Root cause:** The parameter was likely added during an earlier iteration that
planned a DWARF-based visibility heuristic but was never implemented.

**Impact:** No functional impact (dead code), but it:
1. Misleads readers into thinking `DW_AT_external` affects export decisions
2. Wastes a DWARF attribute lookup at every function/variable DIE

**Fix:**
```python
# Before:
is_dwarf_external = _attr_bool(die, "DW_AT_external")
if not self._is_exported(mangled, name, is_dwarf_external=is_dwarf_external):
    return

def _is_exported(self, mangled: str, name: str, *, is_dwarf_external: bool = False) -> bool:

# After:
if not self._is_exported(mangled, name):
    return

def _is_exported(self, mangled: str, name: str) -> bool:
```

**Verification:** The `is_dwarf_external` parameter is removed from
`_is_exported()` and its call sites. Note that `DW_AT_external` is still
read elsewhere in `dwarf_snapshot.py` (lines 349, 414) for other purposes
(e.g. static function detection). The fix only removes the *unused plumbing*
of the attribute into `_is_exported()`.

---

### FIX-B2 — Demangle LRU cache enlargement in `demangle.py`

**File:** `abicheck/demangle.py` line 33

**Problem:**
The `demangle()` function used `@functools.lru_cache(maxsize=4096)`. For
large C++ libraries (e.g. Qt, Boost, LLVM) with more than 4096 unique
mangled symbols, cache eviction caused repeated demangling of the same
symbols during multi-pass processing (detectors + enrichment +
deduplication).

**Root cause:** The original cache size was chosen for small-to-medium
libraries but is insufficient for libraries with heavy C++ template use.

**Impact:** Performance degradation on large C++ libraries due to redundant
`cxxfilt`/subprocess calls. No correctness impact.

**Fix:**
```python
# Before:
@functools.lru_cache(maxsize=4096)

# After:
@functools.lru_cache(maxsize=16384)
```

**Rationale:** 16384 entries at ~200 bytes average per cached demangled name
≈ 3.2 MB memory overhead — negligible for the runtime. This covers the
symbol counts of major C++ libraries (Qt ~12K, Boost.Asio ~8K, LLVM ~15K).

---

### FIX-D — Deduplicate `_COMPILER_INTERNAL_TYPES` to `model.py`

**Files:**
- `abicheck/model.py` lines 33–46 (new canonical location)
- `abicheck/dwarf_snapshot.py` (removed duplicate, imports from model)
- `abicheck/diff_types.py` (also imports from model — added during later refactoring)

**Problem:**
The set `_COMPILER_INTERNAL_TYPES` and its predicate
`_is_compiler_internal_type()` were **defined identically** in both
`checker.py` and `dwarf_snapshot.py`. Any addition or removal of a compiler
internal type required updating both files, with risk of divergence.

**Root cause:** The two modules were developed independently and both needed
to filter compiler-internal types (e.g. `__va_list_tag`, `__int128`).

**Impact:** Maintenance hazard — if one copy was updated but not the other,
types could be filtered in AST analysis but not in DWARF analysis (or vice
versa), leading to false positives from one detector tier only.

**Fix:** Move to `model.py` as single source of truth:

```python
# model.py — new canonical location
COMPILER_INTERNAL_TYPES: frozenset[str] = frozenset({
    "__va_list_tag", "__builtin_va_list", "__gnuc_va_list",
    "__int128", "__int128_t", "__uint128_t",
    "__NSConstantString_tag", "__NSConstantString",
})

def is_compiler_internal_type(name: str) -> bool:
    """Return True if *name* is a compiler internal type that should be excluded."""
    return bool(name) and name in COMPILER_INTERNAL_TYPES
```

```python
# dwarf_snapshot.py — import instead of define
from .model import is_compiler_internal_type as _is_compiler_internal

# diff_types.py — also imports (added during later refactoring)
from .model import is_compiler_internal_type as _is_compiler_internal_type
```

**Note:** `checker.py` does **not** import `is_compiler_internal_type`.
It imports only `AbiSnapshot` from `model.py`. The original duplicate
definition in `checker.py` was removed entirely without a replacement
import, because the checker module delegates type filtering to its
downstream consumers.

**Why `model.py`:** This module already defines the core data model
(`AbiSnapshot`, `Function`, `RecordType`, etc.) and is imported by both
`checker.py` and `dwarf_snapshot.py`. Placing the constant there avoids
circular imports and keeps type-level filtering logic with type definitions.

---

## Problem 3: Logging & Diagnostics

### ~~FIX-I — Type dedup warning throttling~~ (NOT IMPLEMENTED)

**Status:** Not implemented. The `seen_type_dup` set described below does
not exist in the codebase, and the commit `119587b3f` diff does not include
any changes related to type dedup throttling. The `seen_func_dup` /
`seen_var_dup` patterns referenced as prior art also do not exist.

The type dedup warning in `model.py` (line 312) uses a different
aggregation-based approach (collecting duplicates into a dict and logging
a summary), which partially addresses the log noise concern but through
a different mechanism than what was originally proposed.

**Original proposal (not implemented):**

**File:** `abicheck/dwarf_snapshot.py` (not `checker.py` — the
`_DwarfSnapshotBuilder` class lives in `dwarf_snapshot.py`)

Add a `seen_type_dup` throttling set to log only the first occurrence of
each duplicate type name, matching the proposed pattern for functions and
variables.

---

## Summary of Changes

| Fix | File(s) | Lines Changed | Category |
|-----|---------|--------------|----------|
| FIX-A | `dumper.py` | 1 | Detection accuracy |
| FIX-F | `diff_filtering.py` | 8 | Detection accuracy |
| FIX-B1 (param) | `dwarf_snapshot.py` | -10 | Code hygiene |
| FIX-B2 (cache) | `demangle.py` | 1 | Performance |
| FIX-D | `model.py`, `dwarf_snapshot.py` | +15 / -27 | Code dedup |
| ~~FIX-I~~ | — | — | Not implemented |

**Total:** 4 files, +25 / -38 lines (net -13 lines) — excludes FIX-I (not implemented)

---

## Ordering & Dependencies

The fixes are **semantically independent** — they modify different logic
paths with no behavioral interaction. The commit applied them atomically
in `119587b3f`. However, FIX-D and FIX-B1 both modify `dwarf_snapshot.py`,
so they are not file-independent and would require care if cherry-picked
separately.

**Post-processing pipeline impact:** Only FIX-F modifies post-processing
behavior. It tightens `_deduplicate_ast_dwarf()` Pass 3 without changing the
pipeline order or function signatures. No other post-processing functions are
affected.

**Import graph change:** FIX-D adds a `dwarf_snapshot.py → model.py` import
edge for `is_compiler_internal_type`. This edge already exists
(`dwarf_snapshot.py` already imports from `model.py`), so no new dependency
cycles are introduced. `checker.py` is unchanged (no new import added).

---

## Test Coverage

Test file: `tests/test_review_fixes.py` (51 tests across 9 classes)

### Tests mapped to fixes

| Fix | Direct Test | Notes |
|-----|------------|-------|
| FIX-A | **None** | No test exercises the `_CPP_PATTERNS` const-reference regex. `TestCanonicalizeTypeName` (15 tests) tests `canonicalize_type_name()`, which is a separate C3 fix. |
| FIX-F | **None (direct)** | No test constructs nested-type dedup scenarios. Exercised indirectly through `compare()` integration tests in `test_checker.py`. |
| FIX-B1 | **None (direct)** | `TestConfidenceComputation` (4 tests) tests confidence enum semantics, not `_is_exported()`. The dead parameter removal is implicitly validated by passing tests. |
| FIX-B2 | **None** | Cache size is a runtime tuning constant; no test validates it. |
| FIX-D | **Implicit** | Any test using compiler internal types exercises the deduplicated constant. |
| ~~FIX-I~~ | **N/A** | Not implemented. |

### Other test classes in `test_review_fixes.py` (not mapped to spec fixes)

| Test Class | Tests | Area |
|-----------|-------|------|
| `TestCanonicalizeTypeName` | 15 | Type-name canonicalization (C3 fix) |
| `TestParamTypeCanonicalization` | 2 | Parameter type false-positive prevention |
| `TestConfidenceComputation` | 4 | Confidence enum semantics |
| `TestSuppressionAudit` | 10 | Suppression rule staleness/expiry auditing |
| `TestPolicyFileValidateOverrides` | 8 | Policy override validation |
| `TestCanonicalizeNamespaceTypes` | 5 | Namespace type canonicalization |
| `TestUnionFieldCanonicalization` | 1 | Union field prefix handling |
| `TestRenderOutputValidation` | 3 | Output format validation |
| `TestServiceImportPaths` | 3 | Service module import checks |

Additional coverage from `tests/test_report_filtering.py` and
`tests/test_checker.py` which exercise the full `compare()` pipeline
including all fixed code paths.
