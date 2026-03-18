# Fix Specification: abicheck Bug Fixes

**Date:** 2026-03-18
**Based on:** BUG_REPORT.md team review findings
**Scope:** 7 confirmed bugs, 2 design discussions, 2 enhancement requests

---

## Table of Contents

1. [FIX-A: Header C++ Mangling for C Functions (Bug 2 + Bug 11)](#fix-a)
2. [FIX-B: C++ DWARF Function Extraction (Bug 7 + Bug 8)](#fix-b)
3. [FIX-C: Enum Change Deduplication (Bug 3)](#fix-c)
4. [FIX-D: Compiler Internal Type Filtering (Bug 9)](#fix-d)
5. [FIX-E: Stripped Binary Removal Policy (Bug 1)](#fix-e)
6. [FIX-F: Struct Offset Dedup in DWARF-only Mode (Bug 4)](#fix-f)
7. [FIX-G: JSON Per-Change Severity (Bug 5)](#fix-g)
8. [FIX-H: Leaf-Mode JSON Schema (Bug 6)](#fix-h)
9. [FIX-I: Duplicate Mangled Symbol Warnings (Bug 10)](#fix-i)
10. [Test Plan](#test-plan)

---

<a name="fix-a"></a>
## FIX-A: Header C++ Mangling for C Functions (Bug 2 + Bug 11)

**Priority:** P0 (HIGH) — Affects correctness for all C library users with headers
**Bugs addressed:** Bug 2 (func_removed + func_added instead of func_params_changed),
Bug 11 (appcompat 0 relevant changes with headers)

### Root Cause

When `--lang` is not explicitly set to `c`, `dumper.py:293-295` creates the
aggregate header with `.hpp` extension:

```python
force_c = lang and lang.upper() == "C"
agg_ext = ".h" if force_c else ".hpp"
```

This makes castxml apply C++ name mangling to C functions (`add` → `_Z3addii`).
The checker at `checker.py:332-342` matches functions by mangled name, so
parameter changes produce different mangled names → reported as remove+add
instead of parameter change.

Downstream, `appcompat.py:399-408` compares `change.symbol` (mangled C++ name)
against `app.undefined_symbols` (plain C linker names) → no match → 0 relevant.

### Proposed Fix — Three-Part Approach

#### Part 1: Auto-detect C language from headers

**File:** `abicheck/dumper.py` (~line 290)

Add a heuristic to auto-detect C vs C++ from header content when `--lang` is
not explicitly specified:

```python
def _detect_header_language(header_paths: list[Path]) -> str | None:
    """Heuristic: if ALL headers are .h and contain no C++ keywords, assume C."""
    cpp_indicators = {
        b"class ", b"namespace ", b"template<", b"template <",
        b"virtual ", b"public:", b"private:", b"protected:",
        b"std::", b"#include <iostream", b"#include <vector",
        b"#include <string>", b"#include <map>",
    }
    all_dot_h = all(p.suffix == ".h" for p in header_paths)
    if not all_dot_h:
        return None  # mixed extensions, don't guess

    for p in header_paths:
        content = p.read_bytes()
        if any(ind in content for ind in cpp_indicators):
            return None  # C++ detected
    return "c"
```

**Integration point** (dumper.py ~line 293):
```python
if lang is None:
    detected = _detect_header_language(header_paths)
    if detected:
        lang = detected
force_c = lang and lang.upper() == "C"
```

**Trade-off:** Heuristic may misclassify headers that use C++ keywords in
comments or macros. This is acceptable because: (1) users can always override
with `--lang c++`, (2) the false positive rate is low for real-world C headers.

#### Part 2: Use `is_extern_c` flag in function matching

**File:** `abicheck/checker.py` (~line 329)

Currently `_diff_functions()` matches by mangled name only. Add fallback
matching using plain name for extern "C" functions:

```python
def _diff_functions(old: AbiSnapshot, new: AbiSnapshot) -> list[Change]:
    # ... existing map building ...

    # Build secondary index: plain name → function for extern "C"
    old_by_name = {f.name: f for f in old_map.values() if f.is_extern_c}
    new_by_name = {f.name: f for f in new_map.values() if f.is_extern_c}

    for mangled, f_old in old_map.items():
        if mangled in new_map:
            changes.extend(_check_function_signature(mangled, f_old, new_map[mangled]))
            continue

        # Fallback: match extern "C" by plain name
        if f_old.is_extern_c and f_old.name in new_by_name:
            f_new = new_by_name[f_old.name]
            changes.extend(_check_function_signature(f_old.name, f_old, f_new))
            matched_by_name.add(f_old.name)
            continue

        changes.append(_check_removed_function(mangled, f_old, new_all, elf_only_mode))

    for mangled, f_new in new_map.items():
        if mangled not in old_map and not (f_new.is_extern_c and f_new.name in matched_by_name):
            changes.append(Change(kind=ChangeKind.FUNC_ADDED, ...))
```

**Architectural note:** This is a targeted fix that only activates for extern
"C" functions. Pure C++ functions continue to use exact mangled name matching,
which is correct for C++ (overloads produce different mangled names by design).

#### Part 3: Fix appcompat symbol matching

**File:** `abicheck/appcompat.py` (~line 399)

Add demangled/plain name fallback to `_is_relevant_to_app()`:

```python
def _is_relevant_to_app(change: Change, app: AppRequirements) -> bool:
    # Direct symbol match (works for DWARF/ELF names)
    if change.symbol in app.undefined_symbols:
        return True

    # Demangled fallback: strip C++ mangling for comparison
    plain = _demangle_symbol(change.symbol)
    if plain and plain != change.symbol and plain in app.undefined_symbols:
        return True

    # affected_symbols enrichment
    if change.affected_symbols:
        affected = set(change.affected_symbols)
        if app.undefined_symbols & affected:
            return True
        # Also try demangled versions of affected_symbols
        demangled_affected = {_demangle_symbol(s) or s for s in affected}
        if app.undefined_symbols & demangled_affected:
            return True

    # ... rest unchanged ...
```

For `_demangle_symbol()`, use subprocess `c++filt` or the `cxxfilt` Python
package if available, with graceful fallback:

```python
def _demangle_symbol(sym: str) -> str | None:
    """Demangle a C++ symbol to its base name. Returns None if not C++."""
    if not sym.startswith("_Z"):
        return sym  # Already a C name
    try:
        import cxxfilt
        return cxxfilt.demangle(sym)
    except (ImportError, Exception):
        pass
    # Minimal fallback: extract function name from Itanium mangling
    # _Z + length + name pattern
    return None
```

**Alternative approach (simpler):** Since we know the app's symbols are C
linkage names, strip the `_Z...` prefix by extracting just the function name
portion. But this is fragile for nested C++ names, so the `c++filt` approach
is more robust.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/dumper.py` | ~290 | Auto-detect C language from .h headers |
| `abicheck/checker.py` | ~329 | Fallback match extern "C" by plain name |
| `abicheck/appcompat.py` | ~399 | Demangled symbol matching |

---

<a name="fix-b"></a>
## FIX-B: C++ DWARF Function Extraction (Bug 7 + Bug 8)

**Priority:** P0 (HIGH) — C++ DWARF-only analysis is fundamentally broken
**Bugs addressed:** Bug 7 (0 functions in C++ DWARF dump),
Bug 8 (false "no DWARF" warning in compare-release)

### Root Cause

`dwarf_snapshot.py:757-763` checks `_is_exported(mangled, name)`:
- ELF exports contain exact mangled names: `_ZNK6Widget8getValueEv`
- DWARF DW_AT_linkage_name may differ (const qualifier variance, compiler
  variant), or be absent entirely
- DWARF DW_AT_name = `"getValue"` — not in ELF exports (ELF uses mangled names)
- Both checks fail → function rejected

### Proposed Fix — Demangled Name Index

**File:** `abicheck/dwarf_snapshot.py`

Build a **demangled name set** from ELF exports as a fallback:

```python
class DwarfSnapshotBuilder:
    def __init__(self, elf_meta, ...):
        # ... existing code ...
        self._exported_names: set[str] = set()
        self._demangled_exports: set[str] = set()

        if elf_meta.symbols:
            for sym in elf_meta.symbols:
                if sym.name and sym.visibility not in _HIDDEN_VIS:
                    self._exported_names.add(sym.name)
                    # Build demangled index for C++ fallback
                    demangled = _try_demangle(sym.name)
                    if demangled:
                        self._demangled_exports.add(demangled)
```

Update `_is_exported()`:

```python
def _is_exported(self, mangled: str, name: str) -> bool:
    # Exact mangled match (fast path)
    if mangled and mangled in self._exported_names:
        return True
    # Plain name match (C functions)
    if name and name in self._exported_names:
        return True
    # Demangled fallback (C++ with mangling variance)
    if mangled and mangled.startswith("_Z"):
        demangled = _try_demangle(mangled)
        if demangled and demangled in self._demangled_exports:
            return True
    # Name-in-demangled (C++ member functions)
    if name and name in self._demangled_exports:
        # Too broad — would match unrelated functions with same short name.
        # Only use this if scoped name matches (e.g., "Widget::getValue")
        pass
    return False
```

For demangling, use `cxxfilt` package (already commonly available) or
subprocess `c++filt`:

```python
def _try_demangle(sym: str) -> str | None:
    """Best-effort demangle of Itanium C++ name."""
    if not sym.startswith("_Z"):
        return None
    try:
        import cxxfilt
        return cxxfilt.demangle(sym)
    except Exception:
        return None
```

### Architectural Considerations

**Option A (Recommended): Demangle-and-compare at export check time**
- Add `cxxfilt` as optional dependency (it's pure Python, lightweight)
- Build demangled index once per snapshot (~O(n) symbols)
- Check at `_is_exported()` with three tiers: exact → plain → demangled
- Pro: Precise, handles all C++ mangling variants
- Con: New dependency (optional, graceful fallback)

**Option B: Normalize mangled names before comparison**
- Strip const/volatile qualifiers from both ELF and DWARF mangled names
- Simpler but doesn't handle all mangling differences (return type, etc.)
- Pro: No new dependency
- Con: Fragile, incomplete normalization

**Option C: Accept all DWARF subprograms that have DW_AT_external=true**
- DWARF DIEs with `DW_AT_external` are by definition externally visible
- Skip the ELF cross-check entirely for external subprograms
- Pro: Simplest fix, no demangling needed
- Con: May include functions that are declared external in DWARF but not
  actually in .dynsym (e.g., LTO-eliminated functions)

**Recommendation:** Option A with Option C as a fast supplement. Check
DW_AT_external first, then validate against ELF exports using demangled index.

### Bug 8 Fix

Bug 8 (false "no DWARF" warning) will be automatically resolved when Bug 7
is fixed, because the dumper determines "no DWARF" based on whether any
functions were extracted from DWARF. With C++ functions properly extracted,
the warning will not trigger.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/dwarf_snapshot.py` | ~259 | Build demangled export index |
| `abicheck/dwarf_snapshot.py` | ~757 | Three-tier export check |
| `pyproject.toml` | deps | Add `cxxfilt` as optional dependency |

---

<a name="fix-c"></a>
## FIX-C: Enum Change Deduplication (Bug 3)

**Priority:** P1 (MEDIUM) — Inflated change counts affect summaries and CI
**Bug addressed:** Bug 3

### Root Cause

Two detectors produce enum changes with different description strings:
1. `_diff_enums()` (line 643): `"Enum member value changed: Color::GREEN"`
2. `_diff_enum_layouts()` (line 2813): `"Enum member value changed: Color::GREEN (1 → 2)"`

The exact dedup at line 2180 uses `(kind, description)` as the key. Since
descriptions differ, the dedup misses the match. The cross-kind dedup
(`_DWARF_TO_AST_EQUIV`) has no enum entries.

### Proposed Fix — Two Changes

#### Change 1: Add enum kinds to `_DWARF_TO_AST_EQUIV`

**File:** `abicheck/checker.py` (~line 1814)

```python
_DWARF_TO_AST_EQUIV: dict[ChangeKind, set[ChangeKind]] = {
    # ... existing struct mappings ...
    ChangeKind.STRUCT_FIELD_OFFSET_CHANGED: {ChangeKind.TYPE_FIELD_OFFSET_CHANGED},
    # ... etc ...

    # NEW: Enum layout ↔ AST enum dedup
    # Both detectors use the same ChangeKind, so we need same-kind dedup
    # by (kind, symbol) instead of (kind, description)
}
```

However, since both detectors emit the **same ChangeKind** (both are
`ENUM_MEMBER_VALUE_CHANGED`), the cross-kind mapping doesn't help here.
The issue is same-kind, same-symbol, different-description.

#### Change 2: Add symbol-based dedup pass

**File:** `abicheck/checker.py` (~line 2178)

Add a third dedup pass that matches by `(kind, symbol)`:

```python
def _deduplicate_ast_dwarf(changes: list[Change]) -> list[Change]:
    # Pass 1: Exact (kind, description) dedup — existing
    seen_exact: set[tuple[str, str]] = set()
    stage1 = []
    for c in changes:
        key = (c.kind.value, c.description)
        if key in seen_exact:
            continue
        seen_exact.add(key)
        stage1.append(c)

    # Pass 2: Same-kind symbol dedup — NEW
    # When two changes have the same kind AND same symbol but different
    # descriptions, keep the one with more detail (longer description).
    seen_symbol: dict[tuple[str, str], Change] = {}
    stage2 = []
    for c in stage1:
        key = (c.kind.value, c.symbol)
        if key in seen_symbol:
            existing = seen_symbol[key]
            # Keep the more informative description
            if len(c.description) > len(existing.description):
                stage2.remove(existing)
                stage2.append(c)
                seen_symbol[key] = c
            continue
        seen_symbol[key] = c
        stage2.append(c)

    # Pass 3: Cross-kind dedup — existing
    # ... existing _DWARF_TO_AST_EQUIV logic ...
```

**Trade-off:** The `stage2.remove()` is O(n), but the total number of changes
is typically small (<100), so this is acceptable. If performance matters, use
a set of indices instead.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/checker.py` | ~2178 | Add same-kind symbol-based dedup pass |

---

<a name="fix-d"></a>
## FIX-D: Compiler Internal Type Filtering (Bug 9)

**Priority:** P2 (LOW) — False positives, cosmetic but affects counts
**Bug addressed:** Bug 9

### Root Cause

The castxml/header path filters `__`-prefixed types at `dumper.py:616`, but
the DWARF path (`dwarf_snapshot.py`) does not apply any prefix filtering.
`__va_list_tag`, `__builtin_va_list`, `__gnuc_va_list` are included in DWARF
snapshots and reported as ABI changes.

### Proposed Fix

**File:** `abicheck/dwarf_snapshot.py`

Add a shared blocklist and apply it in three locations:

```python
# Module-level constant
_COMPILER_INTERNAL_PREFIXES = ("__",)
_COMPILER_INTERNAL_TYPES = frozenset({
    "__va_list_tag", "__builtin_va_list", "__gnuc_va_list",
    "__int128", "__int128_t", "__uint128_t",
    "__NSConstantString_tag", "__NSConstantString",
})

def _is_compiler_internal(name: str) -> bool:
    """Return True if the type name is a compiler internal."""
    if not name:
        return False
    if name.startswith(_COMPILER_INTERNAL_PREFIXES):
        return True
    return name in _COMPILER_INTERNAL_TYPES
```

Apply at:
1. **Line ~518** (`_process_record_type`):
   ```python
   if _is_compiler_internal(name):
       return
   ```
2. **Line ~662** (`_process_enum`):
   ```python
   if _is_compiler_internal(name):
       return
   ```
3. **Line ~708** (`_process_typedef`):
   ```python
   if _is_compiler_internal(name):
       return
   ```

Also filter in `checker.py` as a defense-in-depth layer:

**File:** `abicheck/checker.py`

Add filtering to `_diff_types()` (~line 427) and `_diff_typedefs()` (~line 894):

```python
old_map = {t.name: t for t in old.types if not _is_compiler_internal(t.name)}
new_map = {t.name: t for t in new.types if not _is_compiler_internal(t.name)}
```

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/dwarf_snapshot.py` | ~518, ~662, ~708 | Filter compiler internals |
| `abicheck/checker.py` | ~427, ~894 | Defense-in-depth filtering |

---

<a name="fix-e"></a>
## FIX-E: Stripped Binary Removal Policy (Bug 1)

**Priority:** P2 — Design discussion, not a code bug
**Bug addressed:** Bug 1

### Current Design (Intentional)

`func_removed_elf_only` is COMPATIBLE across all policies because without
headers, the tool can't confirm a symbol was part of the public API. Many
ELF exports are internal helpers cleaned up between versions.

### Proposed Enhancement: Policy-Level Override

Rather than changing the default (which could cause false positives for
legitimate visibility cleanup), provide explicit knobs:

#### Option 1: New `--strict-elf-only` flag (recommended)

**File:** `abicheck/cli.py`

Add a new flag to the `compare` command:

```python
@click.option("--strict-elf-only", is_flag=True, default=False,
              help="Treat ELF-only symbol removals as BREAKING instead of "
                   "COMPATIBLE. Use when headers are unavailable but all "
                   "exported symbols are part of the public API.")
```

**File:** `abicheck/checker.py`

Pass through to `_check_removed_function()`:

```python
def _check_removed_function(mangled, f_old, new_all, elf_only_mode,
                            strict_elf_only=False):
    if elf_only_mode and f_old.visibility == Visibility.ELF_ONLY:
        if strict_elf_only:
            removed_kind = ChangeKind.FUNC_REMOVED
        else:
            removed_kind = ChangeKind.FUNC_REMOVED_ELF_ONLY
    else:
        removed_kind = ChangeKind.FUNC_REMOVED
```

#### Option 2: Document policy-file override (already works)

Users can already override this with `--policy-file`:

```yaml
base_policy: strict_abi
overrides:
  func_removed_elf_only: break
```

This should be prominently documented in the CLI help and troubleshooting docs.

### Recommendation

Implement Option 1 (`--strict-elf-only` flag) AND enhance documentation for
Option 2. The flag is discoverable from `--help` while the policy file approach
covers advanced use cases.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/cli.py` | compare cmd | Add `--strict-elf-only` flag |
| `abicheck/checker.py` | ~226 | Honor flag in removal logic |
| `docs/user-guide/cli.md` | | Document flag and policy override |
| `docs/troubleshooting.md` | | Add stripped binary guidance |

---

<a name="fix-f"></a>
## FIX-F: Struct Offset Dedup in DWARF-only Mode (Bug 4)

**Priority:** P2 — Design discussion
**Bug addressed:** Bug 4

### Root Cause

In DWARF-only mode, both `type_field_offset_changed` (from DWARF types) and
`struct_field_offset_changed` (from DWARF layout) are emitted. The existing
dedup in `_DWARF_TO_AST_EQUIV` maps:

```python
ChangeKind.STRUCT_FIELD_OFFSET_CHANGED: {ChangeKind.TYPE_FIELD_OFFSET_CHANGED}
```

But dedup fails because the symbols differ:
- `type_field_offset_changed` symbol: `"Point"` (root type)
- `struct_field_offset_changed` symbol: `"Point::x"` (field-qualified)

### Proposed Fix: Normalize symbols during cross-kind dedup

**File:** `abicheck/checker.py` (~line 2186)

```python
# Cross-kind dedup: check by symbol OR parent type match
for c in stage_N:
    equiv_ast_kinds = _DWARF_TO_AST_EQUIV.get(c.kind)
    if not equiv_ast_kinds:
        keep.append(c)
        continue

    # Try exact symbol match
    if any((ak.value, c.symbol) in ast_findings for ak in equiv_ast_kinds):
        continue

    # Try parent type match: "Point::x" → check "Point"
    if "::" in c.symbol:
        parent = c.symbol.rsplit("::", 1)[0]
        if any((ak.value, parent) in ast_findings for ak in equiv_ast_kinds):
            # Verify the field name matches in the description
            field = c.symbol.rsplit("::", 1)[1]
            if any(field in desc for (ak_val, sym), desc
                   in ast_finding_descs.items()
                   if ak_val in {ak.value for ak in equiv_ast_kinds}
                   and sym == parent):
                continue

    keep.append(c)
```

**Simpler alternative:** Match by extracting the field name from both
descriptions and checking if the underlying change is the same field.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/checker.py` | ~2186 | Parent-type fallback in cross-kind dedup |

---

<a name="fix-g"></a>
## FIX-G: JSON Per-Change Severity (Bug 5)

**Priority:** P3 — Enhancement request
**Bug addressed:** Bug 5

### Current Design (Intentional per ADR-014)

Severity is policy-dependent and deliberately omitted from JSON to keep
changes policy-neutral.

### Proposed Enhancement

Add an optional `"severity"` field that materializes the active policy's
classification at report time:

**File:** `abicheck/reporter.py` (~line 505)

```python
def _change_to_dict(change: Change, policy: str = "strict_abi") -> dict:
    d = {
        "kind": change.kind.value,
        "symbol": change.symbol,
        "description": change.description,
        "old_value": change.old_value,
        "new_value": change.new_value,
        "impact": change.impact,
        "affected_symbols": list(change.affected_symbols or []),
        "caused_count": change.caused_count,
        # NEW: materialize severity from active policy
        "severity": _kind_to_severity(change.kind, policy),
    }
    return d

def _kind_to_severity(kind: ChangeKind, policy: str) -> str:
    """Map a ChangeKind to its severity under the given policy."""
    breaking, api_break, compatible, risk = policy_kind_sets(policy)
    if kind in breaking:
        return "breaking"
    if kind in api_break:
        return "api_break"
    if kind in risk:
        return "risk"
    if kind in compatible:
        return "compatible"
    return "unknown"
```

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/reporter.py` | ~505 | Add `severity` field to JSON changes |
| `abicheck/checker_policy.py` | | Export `_kind_to_severity()` helper |

---

<a name="fix-h"></a>
## FIX-H: Leaf-Mode JSON Schema (Bug 6)

**Priority:** P3 — Enhancement request
**Bug addressed:** Bug 6

### Current Design (Intentional, documented)

Leaf mode uses `leaf_changes` and `non_type_changes` keys by design.

### Proposed Enhancement

Populate the `changes` key with the union of both, so naive consumers
still get data:

**File:** `abicheck/reporter.py` (~line 374)

```python
def _to_json_leaf(result, ...):
    d = {
        ...
        "leaf_changes": [...],
        "non_type_changes": [...],
        # Backward-compat: populate changes with union for naive consumers
        "changes": leaf_changes_list + non_type_changes_list,
    }
```

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/reporter.py` | ~374 | Populate `changes` in leaf mode |

---

<a name="fix-i"></a>
## FIX-I: Duplicate Mangled Symbol Warnings (Bug 10)

**Priority:** P3 — Cosmetic
**Bug addressed:** Bug 10

### Root Cause

castxml generates multiple entries per struct (forward decl, typedef, def).
`model.py:188-199` warns on each duplicate.

### Proposed Fix

Deduplicate before indexing, or throttle warnings:

**File:** `abicheck/model.py` (~line 188)

```python
def index(self) -> None:
    func_map: dict[str, Function] = {}
    seen_dup_warning: set[str] = set()
    for f in self.functions:
        if f.mangled in func_map:
            if f.mangled not in seen_dup_warning:
                _model_log.warning(
                    "Duplicate mangled symbol skipped (first-wins): "
                    "%s in %s@%s", f.mangled, self.library, self.version
                )
                seen_dup_warning.add(f.mangled)
        else:
            func_map[f.mangled] = f
```

This ensures each symbol triggers at most 1 warning per index() call
instead of N per duplicate entry.

### Files Changed

| File | Lines | Change |
|------|-------|--------|
| `abicheck/model.py` | ~188 | Throttle duplicate warnings |

---

<a name="test-plan"></a>
## Test Plan

### New Tests for FIX-A (Header C++ Mangling)

**File:** `tests/test_header_c_language.py` (new)

```python
class TestCLanguageAutoDetection:
    """Test auto-detection of C vs C++ for header-based analysis."""

    def test_c_headers_detected_as_c(self):
        """Pure .h headers with no C++ keywords → detected as C."""
        # Create temp .h file with C-only content
        # Assert _detect_header_language returns "c"

    def test_cpp_headers_not_misdetected(self):
        """Headers with class/namespace/template → not detected as C."""
        # Create .h file with "class Widget {"
        # Assert _detect_header_language returns None

    def test_hpp_headers_not_misdetected(self):
        """Files with .hpp extension → not detected as C."""

    def test_mixed_h_hpp_not_detected(self):
        """Mix of .h and .hpp → no auto-detection."""


class TestExternCMatching:
    """Test that extern C functions match by plain name across mangling."""

    def test_c_func_param_change_detected(self):
        """C function with added parameter → func_params_changed, not remove+add."""
        old = _snap(functions=[
            Function(name="add", mangled="_Z3addii", return_type="int",
                     params=[Param("a", "int"), Param("b", "int")],
                     is_extern_c=True)
        ])
        new = _snap(functions=[
            Function(name="add", mangled="_Z3addiii", return_type="int",
                     params=[Param("a", "int"), Param("b", "int"), Param("c", "int")],
                     is_extern_c=True)
        ])
        result = compare(old, new)
        kinds = {c.kind for c in result.changes}
        assert ChangeKind.FUNC_PARAMS_CHANGED in kinds
        assert ChangeKind.FUNC_REMOVED not in kinds
        assert ChangeKind.FUNC_ADDED not in kinds

    def test_cpp_overload_still_uses_mangled(self):
        """C++ overloaded functions must NOT match by plain name."""
        # Two different C++ overloads: foo(int) and foo(string)
        # Should match by mangled name, not by plain "foo"

    def test_extern_c_pointer_level_change(self):
        """C function pass-by-value → pointer → param_pointer_level_changed."""


class TestAppcompatWithHeaders:
    """Test appcompat symbol matching when headers use C++ mangling."""

    def test_relevant_changes_nonzero_with_headers(self, shared_cmake_build_dir):
        """appcompat with -H should find relevant changes, not 0."""
        # Integration test: compile v1/v2, build app, run appcompat with -H
        # Assert relevant_changes > 0

    def test_relevance_matches_dwarf_only(self, shared_cmake_build_dir):
        """appcompat with -H should find similar relevant changes as DWARF-only."""
```

### New Tests for FIX-B (C++ DWARF Functions)

**File:** `tests/test_dwarf_snapshot.py` (extend existing)

```python
class TestCppDwarfFunctionExtraction:
    """Test that C++ member functions are extracted from DWARF."""

    @pytest.mark.integration
    def test_cpp_member_functions_extracted(self):
        """C++ member functions should appear in DWARF dump."""
        # Compile: g++ -g -shared -fPIC -o lib.so widget.cpp
        # Run: dump lib.so --dwarf-only
        # Assert: len(snapshot.functions) > 0
        # Assert: "getValue" or "_ZNK6Widget8getValueEv" in function names

    @pytest.mark.integration
    def test_cpp_const_method_matches_elf(self):
        """const method DWARF name should match ELF export."""
        # Verify _is_exported handles const qualifier variance

    @pytest.mark.integration
    def test_cpp_virtual_destructor_extracted(self):
        """Virtual destructors should be extracted from DWARF."""

    def test_is_exported_demangled_fallback(self):
        """_is_exported falls back to demangled name comparison."""
        builder = DwarfSnapshotBuilder(elf_meta=mock_elf)
        builder._exported_names = {"_ZNK6Widget8getValueEv"}
        builder._demangled_exports = {"Widget::getValue() const"}
        # Mangled name WITHOUT const:
        assert builder._is_exported("_ZN6Widget8getValueEv", "getValue") is True
```

### New Tests for FIX-C (Enum Dedup)

**File:** `tests/test_report_metadata.py` (extend TestDeduplication)

```python
class TestEnumDeduplication:
    """Test that enum changes from AST and DWARF are deduplicated."""

    def test_same_enum_change_different_description_deduped(self):
        """Two enum changes with same kind+symbol but different descriptions."""
        changes = [
            Change(kind=ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
                   symbol="Color::GREEN",
                   description="Enum member value changed: Color::GREEN",
                   old_value="1", new_value="2"),
            Change(kind=ChangeKind.ENUM_MEMBER_VALUE_CHANGED,
                   symbol="Color::GREEN",
                   description="Enum member value changed: Color::GREEN (1 → 2)",
                   old_value="1", new_value="2"),
        ]
        deduped = _deduplicate_ast_dwarf(changes)
        # Should keep only 1 (the more informative one)
        assert len([c for c in deduped
                    if c.kind == ChangeKind.ENUM_MEMBER_VALUE_CHANGED
                    and "GREEN" in c.symbol]) == 1

    def test_different_enum_members_not_deduped(self):
        """Changes to different enum members should NOT be deduplicated."""
        # Color::GREEN and Color::BLUE should both remain
```

### New Tests for FIX-D (Compiler Internal Types)

**File:** `tests/test_dwarf_snapshot.py` (extend)

```python
class TestCompilerInternalFiltering:
    """Test that compiler internal types are filtered from DWARF snapshots."""

    @pytest.mark.integration
    def test_va_list_tag_filtered(self):
        """__va_list_tag should not appear in DWARF snapshot types."""
        # Compile C file with variadic function
        # Dump with --dwarf-only
        # Assert __va_list_tag not in type names

    @pytest.mark.integration
    def test_builtin_va_list_filtered(self):
        """__builtin_va_list should not appear in typedefs."""

    def test_is_compiler_internal_positive(self):
        """Verify _is_compiler_internal catches known patterns."""
        assert _is_compiler_internal("__va_list_tag")
        assert _is_compiler_internal("__builtin_va_list")
        assert _is_compiler_internal("__gnuc_va_list")
        assert _is_compiler_internal("__int128")

    def test_is_compiler_internal_negative(self):
        """Verify _is_compiler_internal doesn't filter user types."""
        assert not _is_compiler_internal("Point")
        assert not _is_compiler_internal("MyRecord")
        assert not _is_compiler_internal("va_list_wrapper")  # user type
```

### New Tests for FIX-E (Stripped Binary Policy)

**File:** `tests/test_checker.py` (extend)

```python
class TestStrictElfOnlyMode:
    """Test --strict-elf-only flag behavior."""

    def test_func_removed_elf_only_default_compatible(self):
        """Default: ELF-only removal is COMPATIBLE."""
        # existing test at line 288, verify still passes

    def test_func_removed_elf_only_strict_breaking(self):
        """With strict_elf_only: ELF-only removal is BREAKING."""
        old = _snap(functions=[_pub_func("foo", vis=Visibility.ELF_ONLY)],
                    elf_only_mode=True)
        new = _snap(functions=[])
        result = compare(old, new, strict_elf_only=True)
        assert result.verdict == Verdict.BREAKING
        assert any(c.kind == ChangeKind.FUNC_REMOVED for c in result.changes)

    def test_policy_file_override(self):
        """Policy file can upgrade func_removed_elf_only to BREAKING."""
```

### New Tests for FIX-F (Struct Offset Dedup)

**File:** `tests/test_report_metadata.py` (extend TestDeduplication)

```python
class TestCrossKindDedup:
    """Test cross-kind dedup with parent::field symbol matching."""

    def test_struct_offset_deduped_with_type_offset(self):
        """struct_field_offset_changed(Point::x) deduped with type_field_offset_changed(Point)."""
        changes = [
            Change(kind=ChangeKind.TYPE_FIELD_OFFSET_CHANGED,
                   symbol="Point",
                   description="Field offset changed: Point::x (0 → 32 bits)"),
            Change(kind=ChangeKind.STRUCT_FIELD_OFFSET_CHANGED,
                   symbol="Point::x",
                   description="Field offset changed: Point::x (+0 → +4)"),
        ]
        deduped = _deduplicate_ast_dwarf(changes)
        # Should keep only the AST (type_field) version
        assert len(deduped) == 1
        assert deduped[0].kind == ChangeKind.TYPE_FIELD_OFFSET_CHANGED
```

### Integration Test: Full Round-Trip

**File:** `tests/test_bug_fixes_integration.py` (new)

```python
@pytest.mark.integration
class TestBugFixIntegration:
    """End-to-end tests for all bug fixes using real compiled libraries."""

    def test_c_library_header_compare_no_false_removals(self):
        """C library compared with -H should not report false func_removed."""
        # Compile v1.c/v2.c where add() gains a parameter
        # abicheck compare v1.so v2.so -H v1.h --new-header v2.h
        # Assert no func_removed for 'add', assert func_params_changed present

    def test_cpp_dwarf_only_extracts_functions(self):
        """C++ library DWARF-only dump should have non-zero functions."""
        # Compile cpplib.cpp with -g
        # abicheck dump lib.so --dwarf-only
        # Assert functions count > 0

    def test_stripped_library_strict_mode(self):
        """Stripped library with --strict-elf-only catches func removal."""
        # Strip libs, abicheck compare --strict-elf-only
        # Assert exit code 4

    def test_compare_release_cpp_uses_dwarf(self):
        """compare-release should use DWARF for C++ libraries."""
        # Create release dirs with debug C++ libs
        # Assert no "no DWARF" warning in stderr

    def test_enum_changes_not_duplicated(self):
        """Enum value changes should be counted once, not twice."""
        # Compile with enum value change
        # abicheck compare --dwarf-only
        # Count enum_member_value_changed for each member = exactly 1

    def test_appcompat_with_headers_finds_relevant(self):
        """appcompat with -H should report non-zero relevant changes."""
        # Build app + v1/v2 libs with headers
        # Assert relevant_changes > 0

    def test_no_compiler_internal_types_in_dwarf(self):
        """DWARF-only compare should not report __va_list_tag changes."""
        # Compile with variadic function that changes
        # Assert no change with symbol containing "__va_list"
```

---

## Implementation Order

Recommended implementation sequence based on dependencies and risk:

| Phase | Fix | Est. Complexity | Dependencies |
|-------|-----|-----------------|--------------|
| 1 | FIX-D (compiler internals) | Small | None — isolated filter addition |
| 1 | FIX-I (duplicate warnings) | Small | None — isolated change |
| 1 | FIX-C (enum dedup) | Small | None — extends existing dedup |
| 2 | FIX-B (C++ DWARF functions) | Medium | Needs cxxfilt or DW_AT_external |
| 2 | FIX-F (struct offset dedup) | Medium | Extends dedup logic from FIX-C |
| 3 | FIX-A (header C mangling) | Large | FIX-B for demangling infra |
| 3 | FIX-E (strict ELF-only) | Small | None — new flag |
| 4 | FIX-G (JSON severity) | Small | None — additive |
| 4 | FIX-H (leaf JSON schema) | Small | None — additive |

**Phase 1** (quick wins): FIX-C, FIX-D, FIX-I — small, isolated changes
**Phase 2** (core fixes): FIX-B, FIX-F — need careful design for demangling
**Phase 3** (high-impact): FIX-A, FIX-E — highest user impact, most testing needed
**Phase 4** (enhancements): FIX-G, FIX-H — additive, no risk

---

## Architectural Notes

### Shared Demangling Infrastructure

FIX-A and FIX-B both need C++ name demangling. Create a shared utility:

**File:** `abicheck/demangle.py` (new)

```python
"""Shared C++ name demangling utilities."""

import functools
import subprocess

@functools.lru_cache(maxsize=4096)
def demangle(symbol: str) -> str | None:
    """Demangle Itanium C++ symbol. Returns None if not C++."""
    if not symbol or not symbol.startswith("_Z"):
        return None
    try:
        import cxxfilt
        return cxxfilt.demangle(symbol)
    except ImportError:
        pass
    try:
        result = subprocess.run(
            ["c++filt", symbol],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def base_name(symbol: str) -> str:
    """Extract the unqualified function name from a symbol.

    Examples:
        "_ZNK6Widget8getValueEv" → "getValue"
        "Widget::getValue() const" → "getValue"
        "add" → "add"
    """
    demangled = demangle(symbol)
    if demangled:
        # Strip return type, params, qualifiers: "int Widget::getValue() const" → "getValue"
        # Find last :: before (
        paren = demangled.find("(")
        if paren != -1:
            prefix = demangled[:paren]
        else:
            prefix = demangled
        parts = prefix.rsplit("::", 1)
        return parts[-1].strip()
    return symbol
```

### Non-Regression Guarantee

All existing tests MUST continue to pass. The changes are designed to be
backward-compatible:
- FIX-A adds fallback matching (existing exact matching is tried first)
- FIX-B adds fallback export checking (existing exact check is tried first)
- FIX-C adds a dedup pass (reduces output, doesn't add new changes)
- FIX-D filters types (may reduce change count; if this breaks golden tests,
  update the golden files)
- FIX-E is opt-in (new flag, default behavior unchanged)

### Risk Assessment

| Fix | Risk | Mitigation |
|-----|------|-----------|
| FIX-A | Medium — heuristic may misclassify | --lang override always available |
| FIX-B | Medium — demangling adds dependency | cxxfilt optional, subprocess fallback |
| FIX-C | Low — only removes duplicates | Keeps the more informative description |
| FIX-D | Low — only removes noise | Explicit blocklist, easy to extend |
| FIX-E | None — opt-in flag | Default behavior unchanged |
| FIX-F | Low — extends dedup | Only activates for cross-kind pairs |
| FIX-G | None — additive field | Existing JSON consumers unaffected |
| FIX-H | None — additive field | Existing leaf_changes key unchanged |
| FIX-I | None — reduces warnings | Same warning, just throttled |
