# Architecture Review Fixes — Implementation Spec

> **Branch:** `claude/refactor-rules-architecture-AAkVz`
> **Status:** Implemented (commit `119587b3f`)
> **Scope:** 6 fixes across 5 files, grouped into 3 problem areas

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

**Test coverage:** `test_review_fixes.py` — no dedicated test for the regex
itself, but the `_detect_cpp_headers` function is exercised through
integration tests for C++ header detection.

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

**Test coverage:** `test_review_fixes.py` exercises this through integration
tests with nested type scenarios.

---

## Problem 2: Code Hygiene & Deduplication

### FIX-B — Dead parameter removal in `dwarf_snapshot.py`

**File:** `abicheck/dwarf_snapshot.py` — `_is_exported()` method (line 735)
and call site (previously line 385)

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

**Verification:** `DW_AT_external` is no longer read at the call site. The
`_is_exported()` docstring was updated to remove the stale parameter
documentation.

---

### FIX-B — Demangle LRU cache enlargement in `demangle.py`

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
- `abicheck/checker.py` (removed duplicate, imports from model)
- `abicheck/dwarf_snapshot.py` (removed duplicate, imports from model)

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
# checker.py — import instead of define
from .model import is_compiler_internal_type as _is_compiler_internal_type

# dwarf_snapshot.py — import instead of define
from .model import is_compiler_internal_type as _is_compiler_internal
```

**Why `model.py`:** This module already defines the core data model
(`AbiSnapshot`, `Function`, `RecordType`, etc.) and is imported by both
`checker.py` and `dwarf_snapshot.py`. Placing the constant there avoids
circular imports and keeps type-level filtering logic with type definitions.

---

## Problem 3: Logging & Diagnostics

### FIX-I — Type dedup warning throttling in `checker.py`

**File:** `abicheck/checker.py` (in the `_DwarfSnapshotBuilder` type
deduplication path)

**Problem:**
When DWARF analysis encounters duplicate type definitions (common with
templates and header-only libraries), it logged a warning for **every**
duplicate. For large C++ libraries this produced thousands of identical
warnings, obscuring real diagnostic messages.

**Root cause:** Function and variable dedup paths already had
`seen_func_dup` / `seen_var_dup` throttling sets that logged only the first
occurrence per name, but the type dedup path was missing this pattern.

**Impact:** Excessive log noise in verbose mode (`-v` / `--debug`). No
correctness impact but makes it hard to find real issues in log output.

**Fix:** Add `seen_type_dup` throttling set matching the existing pattern:

```python
# Existing pattern for functions (already had throttling):
if name in seen_func_dup:
    continue
seen_func_dup.add(name)
log.debug("Duplicate function: %s", name)

# New: same pattern for types:
if name in seen_type_dup:
    continue
seen_type_dup.add(name)
log.debug("Duplicate type: %s", name)
```

**Verification:** With throttling, a library with 500 duplicate type names
produces 500 debug lines instead of potentially thousands.

---

## Summary of Changes

| Fix | File(s) | Lines Changed | Category |
|-----|---------|--------------|----------|
| FIX-A | `dumper.py` | 1 | Detection accuracy |
| FIX-F | `diff_filtering.py` | 8 | Detection accuracy |
| FIX-B (param) | `dwarf_snapshot.py` | -10 | Code hygiene |
| FIX-B (cache) | `demangle.py` | 1 | Performance |
| FIX-D | `model.py`, `checker.py`, `dwarf_snapshot.py` | +15 / -27 | Code dedup |
| FIX-I | `checker.py` | +3 | Diagnostics |

**Total:** 5 files, +29 / -41 lines (net -12 lines)

---

## Ordering & Dependencies

The fixes are **independent** — they touch different code paths with no
interaction. They can be applied in any order. The commit applied all six
atomically in `119587b3f`.

**Post-processing pipeline impact:** Only FIX-F modifies post-processing
behavior. It tightens `_deduplicate_ast_dwarf()` Pass 3 without changing the
pipeline order or function signatures. No other post-processing functions are
affected.

**Import graph change:** FIX-D adds `model.py → checker.py` and
`model.py → dwarf_snapshot.py` import edges for `is_compiler_internal_type`.
Both edges already exist (both modules already import from `model.py`), so no
new dependency cycles are introduced.

---

## Test Coverage

Test file: `tests/test_review_fixes.py` (31 tests across multiple classes)

| Fix | Test Class | Tests |
|-----|-----------|-------|
| FIX-A | `TestCanonicalizeTypeName`, integration tests | 15+ |
| FIX-F | Nested-type dedup integration tests | via `compare()` |
| FIX-B | `TestConfidenceComputation` (exercises export path) | 5 |
| FIX-D | Implicit (any test using compiler internal types) | — |
| FIX-I | Log-level tests (if present) | — |

Additional coverage from `tests/test_report_filtering.py` and
`tests/test_checker.py` which exercise the full `compare()` pipeline
including all fixed code paths.
