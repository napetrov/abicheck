# Tool Comparison & Gap Analysis: abicheck vs abicc vs libabigail

> Generated 2026-03-24. Based on abicheck v0.2.0 (143+ ChangeKinds),
> abi-compliance-checker 2.3, and libabigail 2.x (abidiff).

---

## Executive Summary

**abicheck already covers all detection categories from both abicc and libabigail,
plus several areas where it exceeds both.** There are no *missing* detection
categories. However, there are a handful of edge-case scenarios from their test
suites that could strengthen our regression coverage.

| Dimension | abicheck | abicc | libabigail |
|-----------|:--------:|:-----:|:----------:|
| Total change kinds | **143+** | ~100 | ~40 named |
| Platforms | ELF, PE, Mach-O | ELF only | ELF only |
| Header analysis | castxml (GCC/Clang/MSVC) | GCC headers or abi-dumper | No (DWARF only) |
| Debug info | DWARF + PDB + BTF/CTF | DWARF (via abi-dumper) | DWARF + CTF/BTF |
| Preprocessor constants | Yes | Yes | No |
| Kernel ABI (KMI) | No | No | Yes (kmidiff) |
| Package-level diff | No | No | Yes (abipkgdiff) |

---

## Detailed Comparison by Detection Category

### 1. Symbol-Level Changes

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Function removed | `func_removed` | Yes | Yes | Full parity |
| Function added | `func_added` | Yes | Yes | Full parity |
| Variable removed | `var_removed` | Yes | Yes | Full parity |
| Variable added | `var_added` | Yes | Yes | Full parity |
| Visibility change (default→hidden) | `func_visibility_changed` | Yes | Yes | Full parity |
| Symbol binding change (GLOBAL↔WEAK) | `symbol_binding_changed` | No | Partial | abicheck unique |
| Symbol type change (FUNC↔OBJECT) | `symbol_type_changed` | No | No | **abicheck unique** |
| Symbol size change (st_size) | `symbol_size_changed` | No | No | **abicheck unique** |
| IFUNC transitions | `ifunc_introduced/removed` | No | No | **abicheck unique** |
| Batch symbol rename detection | `symbol_renamed_batch` | No | No | **abicheck unique** (heuristic) |
| Function likely renamed (fingerprint) | `func_likely_renamed` | No | No | **abicheck unique** |

### 2. Function Signature Changes

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Return type changed | `func_return_changed` | Yes | Yes* | *libabigail only via DWARF, misses without `--headers-dir` |
| Parameter type changed | `func_params_changed` | Yes | Yes* | Same caveat as return type |
| Parameter added/removed | `func_params_changed` | Yes | Yes | |
| Parameter renamed | `param_renamed` | Yes | No | abicc partial |
| Default value removed | `param_default_value_removed` | Yes | No | |
| Default value changed | `param_default_value_changed` | Yes | No | |
| const/volatile on this changed | `func_cv_changed` | Yes | Yes | |
| noexcept added/removed | `func_noexcept_added/removed` | Yes | No | |
| Static↔non-static | `func_static_changed` | Yes | Yes | |
| restrict qualifier change | `param_restrict_changed` | Yes | Yes | |
| va_list transitions | `param_became/lost_va_list` | Yes | No | |
| Pointer level change | `param_pointer_level_changed` | Yes | Partial | |

### 3. Type / Struct Layout

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Size changed | `type_size_changed` | Yes | Yes | |
| Alignment changed | `type_alignment_changed` | Yes | Yes | Yes | |
| Field removed | `type_field_removed` | Yes | Yes | Yes | |
| Field added | `type_field_added` | Yes | Yes | Yes | |
| Field offset changed | `type_field_offset_changed` | Yes | Yes | Yes | |
| Field type changed | `type_field_type_changed` | Yes | Yes | Yes | |
| Field renamed | `field_renamed` | Yes | No | **abicheck unique** |
| Type removed | `type_removed` | Yes | Yes | Partial |
| Type became opaque | `type_became_opaque` | Yes | Yes | Yes | Full parity |
| struct↔union kind change | `type_kind_changed` | Yes | Partial | No |
| struct↔class kind change | `source_level_kind_changed` | Yes | No | No | **abicheck unique** |
| Struct packing changed | `struct_packing_changed` | Yes | No | No | **abicheck unique** (DWARF) |
| Anonymous struct/union changes | `anon_field_changed` | Yes | Partial | Partial |
| Used reserved field | `used_reserved_field` | Yes | No | No | **abicheck unique** |
| Bitfield width/position changed | `field_bitfield_changed` | Yes | Yes | Yes | |

### 4. C++ Virtual Table

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Vtable reorder | `type_vtable_changed` | Yes* | Yes | *abicc misses in XML descriptor mode |
| Virtual method added | `func_virtual_added` | Yes | Yes | |
| Virtual method removed | `func_virtual_removed` | Yes | Yes | |
| Pure virtual added | `func_pure_virtual_added` | Yes | Yes | |
| Virtual became pure | `func_virtual_became_pure` | Yes | Yes | |
| Removed const overload | `removed_const_overload` | Yes | No | **abicheck unique** |

### 5. Inheritance / Base Class

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Base class changed | `type_base_changed` | Yes | Yes | |
| Base class position changed | `base_class_position_changed` | Yes | Yes | Yes | |
| Base class virtual changed | `base_class_virtual_changed` | Yes | Yes | Yes | |

### 6. Enum Changes

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Member removed | `enum_member_removed` | Yes | Yes | |
| Member value changed | `enum_member_value_changed` | Yes | Yes | Partial† | †libabigail conservative |
| Sentinel value changed | `enum_last_member_value_changed` | Yes | No | No | **abicheck unique** |
| Member added | `enum_member_added` | Yes | Yes | Partial |
| Member renamed | `enum_member_renamed` | Yes | No | No | **abicheck unique** |
| Underlying size changed | `enum_underlying_size_changed` | Yes | Yes | Yes | |

### 7. Typedef

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Typedef removed | `typedef_removed` | Yes | Partial | Partial |
| Typedef base changed | `typedef_base_changed` | Yes | Partial | Partial |

### 8. Union-Specific

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Field removed | `union_field_removed` | Yes | Yes | Yes |
| Field type changed | `union_field_type_changed` | Yes | Yes | Yes |
| Field added | `union_field_added` | Yes | Yes | Yes |

### 9. ELF Platform-Specific

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| SONAME changed | `soname_changed` | No | Yes | |
| SONAME bump advisory | `soname_bump_recommended/unnecessary` | No | No | **abicheck unique** |
| Version node removed | `symbol_version_node_removed` | No | Partial | |
| Version definition removed | `symbol_version_defined_removed` | No | No | |
| Version required added | `symbol_version_required_added` | No | No | **abicheck unique** |
| NEEDED added/removed | `needed_added/removed` | No | Partial | |
| RPATH/RUNPATH changed | `rpath_changed/runpath_changed` | No | No | **abicheck unique** |
| Common symbol risk | `common_symbol_risk` | No | No | **abicheck unique** |
| Version script missing | `version_script_missing` | No | No | **abicheck unique** |
| Symbol moved version node | `symbol_moved_version_node` | No | No | **abicheck unique** |

### 10. DWARF / Advanced Detection

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Calling convention changed | `calling_convention_changed` | No | Yes | Via DWARF DW_AT_calling_convention |
| Type visibility (RTTI) changed | `type_visibility_changed` | No | Yes | |
| Toolchain flag drift | `toolchain_flag_drift` | No | No | **abicheck unique** |
| Debug info missing warning | `dwarf_info_missing` | No | Partial | |
| Non-trivial dtor calling conv | VALUE_ABI_TRAIT_CHANGED | No | No | **abicheck unique** (DWARF) |

### 11. Preprocessor / Source-Level

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Constant changed | `constant_changed` | Yes | **No** | libabigail has no header analysis |
| Constant added | `constant_added` | Yes | **No** | |
| Constant removed | `constant_removed` | Yes | **No** | |
| Func became inline | `func_became_inline` | No | **No** | **abicheck unique** (castxml) |
| Func lost inline | `func_lost_inline` | No | **No** | **abicheck unique** |
| Access level changes | `method/field/var_access_changed` | Yes | **No** | abicc partial |
| Field qualifiers (const/volatile/mutable) | 6 ChangeKinds | No | **No** | **abicheck unique** |

### 12. Variable-Specific

| Check | abicheck | abicc | libabigail | Notes |
|-------|:--------:|:-----:|:----------:|-------|
| Variable type changed | `var_type_changed` | Yes | Yes | |
| Variable became const | `var_became_const` | Yes | Partial | No |
| Variable lost const | `var_lost_const` | Yes | Partial | No |
| Variable value changed | `var_value_changed` | Yes | Yes | No |
| Variable access changed | `var_access_changed` | Yes | Yes | No |

---

## What abicheck Detects That NEITHER abicc NOR libabigail Does

1. **Non-trivial destructor calling convention change** (VALUE_ABI_TRAIT_CHANGED) — DWARF value-ABI trait analysis
2. **Inline function annotation changes** (`func_became_inline`, `func_lost_inline`)
3. **Struct packing changes** (`struct_packing_changed`) via DWARF
4. **Toolchain flag drift** (`toolchain_flag_drift`)
5. **Batch symbol rename detection** (`symbol_renamed_batch`) — heuristic
6. **Function likely renamed** (`func_likely_renamed`) — binary fingerprint
7. **SONAME bump advisories** (`soname_bump_recommended/unnecessary`)
8. **ELF version script analysis** (`version_script_missing`, `symbol_moved_version_node`)
9. **Field qualifiers** (const, volatile, mutable changes on struct fields)
10. **Enum member rename** and **sentinel value change** detection
11. **struct↔class source-level kind change** detection
12. **Reserved field usage** detection
13. **Cross-platform support** (PE/Mach-O — both other tools are ELF-only)

---

## What abicc/libabigail Detect That abicheck Does NOT

### libabigail only:
1. **Kernel Module Interface (KMI) comparison** (`kmidiff`) — for Linux kernel modules
2. **Package-level ABI diff** (`abipkgdiff`) — RPM/deb package comparison
3. **Application compatibility check** (`abicompat`) — check app against newer lib

### abicc only:
1. **`-check-implementation`** — disassembly comparison for implementation changes (optional, not ABI)

### Shared gap:
1. **`= delete` detection** — neither abicc nor abicheck detect `= delete` via castxml (castxml omits deleted functions). Known gap documented in test_abicc_parity.py `func_deleted_marker` case.

---

## Test Case Parity Status

### abicc Parity Tests (test_abicc_parity.py)

| Category | Cases | Status |
|----------|:-----:|--------|
| Confirmed parity (both agree) | 12 | fn_removed, fn_added, no_change, return_type, param_type, enum_value, visibility_hidden, multi_fn_removed, multi_fn_added, enum_member_removed, var_removed, typedef_derived_false_base_change, func_deleted_marker, type_became_opaque, global_var_type_widened, no_spurious_visibility_change |
| abicheck correct (we detect, abicc misses) | 5 | vtable_reorder, struct_size, nontrivial_dtor_calling_convention (x2), func_became_inline |
| Known divergence | 0 | (none remaining) |
| Risk (needs human review) | 1 | func_lost_inline |

### libabigail Parity Tests (test_abidiff_parity.py)

| Category | Cases | Status |
|----------|:-----:|--------|
| Confirmed parity (both agree) | 5 | fn_removed, fn_added, no_change, visibility_hidden, vtable_reorder |
| abicheck correct (we detect, abidiff misses) | 2 | return_type, param_type |
| Known divergence | 2 | struct_size, enum_value (abicheck stricter by design) |

### Unit Parity Tests (test_abicc_full_parity.py)

**50/50 passing** — covers VAR_VALUE_CHANGED, TYPE_KIND_CHANGED, USED_RESERVED_FIELD, REMOVED_CONST_OVERLOAD, PARAM_RESTRICT_CHANGED, PARAM_BECAME_VA_LIST, PARAM_LOST_VA_LIST, CONSTANT_CHANGED/ADDED/REMOVED, VAR_ACCESS_CHANGED, SYMBOL_RENAMED_BATCH.

---

## Remaining Gaps to Close

### Priority 1 — Missing from abicc's ~300 embedded test cases

abicc has ~100 C and ~200 C++ test cases embedded in `abi-compliance-checker.pl`. Our parity suite covers ~20 scenarios. The following abicc test categories are **not yet in our parity tests** (though abicheck likely detects them — tests are just missing):

1. **Recursive type changes** — type changes propagated through nested struct/pointer chains
2. **Function pointer parameter changes** — `typedef void (*cb)(int)` → `typedef void (*cb)(long)`
3. **Multiple inheritance edge cases** — diamond inheritance, virtual base reordering
4. **Exception specification changes** — `throw()` → `noexcept` (C++11 migration)
5. **Name mangling edge cases** — operator overloads, conversion operators
6. **Explicit template instantiation changes** — `template class Foo<int>` size changes
7. **Opaque pointer transitions** (forward decl → full definition and vice versa)
8. **Moved/split fields across anonymous unions** inside structs

### Priority 2 — Missing from libabigail's test corpus

libabigail's `tests/` directory contains hundreds of pre-built ELF pairs. We should mirror key scenarios:

1. **CTF/BTF-based comparison** — libabigail supports CTF and BTF as alternatives to DWARF
2. **Large-scale regression** — libabigail tests against ~25,000 Fedora packages
3. **ABIXML round-trip** — serialization/deserialization consistency (our JSON snapshot analog)
4. **Suppression specification parity** — ensure our YAML suppressions cover libabigail's `.abignore` patterns

### Priority 3 — Feature gaps (not detection gaps)

1. **Kernel ABI (KMI) support** — `kmidiff` equivalent for Linux kernel module comparison
2. **Package-level diff** — `abipkgdiff` equivalent for RPM/deb
3. **`= delete` detection** — requires alternative to castxml (DWARF or Clang AST)

---

## Recommendations

1. **No urgent detection gaps exist** — abicheck covers all ABI change categories from both tools, plus 13+ unique detections.

2. **Expand parity test coverage** — Add the ~15 missing abicc test scenarios (P1 above) to our parity suite. These are likely already detected but not regression-tested.

3. **Mirror libabigail ELF test pairs** — Import 10-20 representative pre-built ELF pairs from libabigail's test corpus as integration tests.

4. **Consider `= delete` detection** — Both abicc and abicheck miss this. Implementing it (via DWARF `DW_AT_deleted` or Clang AST) would give us an edge over both tools.

5. **KMI/package-level are out of scope** — These are distribution-specific tools, not ABI compatibility checkers. They can be built on top of abicheck's Python API if needed.
