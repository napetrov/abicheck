# Test Gap Plan — Scanner Accuracy & Coverage Enhancement

## Current State (Post Enhancement)

- **139 existing test files** + **15 new test files** = 154 test files
- **4,516 existing tests** + **906 new tests** = 5,422 total
- All **143 ChangeKind** values referenced in tests
- **80% code coverage** gate in CI

### New Test Files Added

| File | Tests | Purpose |
|------|-------|---------|
| `test_bidirectional_symmetry.py` | 35 | Verify v1->v2 and v2->v1 produce symmetric ChangeKind pairs |
| `test_diff_symbols_deep.py` | 39 | Deep detection tests for 20+ symbol-level ChangeKinds |
| `test_diff_types_deep.py` | 28 | Deep detection tests for type/enum/union/bitfield/qualifier ChangeKinds |
| `test_diff_platform_deep.py` | 37 | ELF/DWARF/PE/Mach-O detector tests with synthetic metadata |
| `test_multi_detector_interaction.py` | 12 | AST+DWARF dedup, redundancy filtering, cross-detector behavior |
| `test_confidence_evidence.py` | 16 | Confidence tier and evidence source assertions |
| `test_false_positive_resistance.py` | 30 | Systematic FP prevention for hidden symbols, additions, ELF metadata |
| `test_policy_override_matrix.py` | 619 | Exhaustive ChangeKind × policy matrix, PolicyFile overrides |
| `test_symbol_versioning_coexistence.py` | 17 | Version node add/remove, aliases, required versions |
| `test_suppression_edge_cases.py` | 26 | Expiration, pattern matching, audit trail, policy interaction |
| `test_parallel_safety.py` | 6 | Concurrent compare() calls, no global state leakage |
| `test_stripped_degradation.py` | 20 | DWARF stripping, confidence degradation, ELF-only mode |
| `test_cross_compiler_fp.py` | 7 | Cross-compiler (gcc vs clang) false positive prevention |
| `test_abidiff_parity_extended.py` | 8 | Extended abidiff parity tests for C/C++ scenarios |
| `test_realworld_scan.py` | 6 | Real-world library release pattern tests |

---

## Remaining Gaps — Prioritized

### P0 — Critical (Should block next release)

#### 1. Stripped Binary Graceful Degradation — DONE
**Status:** Fully implemented:
- `test_stripped_degradation.py` (20 tests) — synthetic metadata scenarios
- `test_cross_compiler_fp.py::TestStrippedVsUnstrippedFP` — real `strip -g` integration test

#### 2. Differential Testing vs abidiff — EXTENDED
**Status:** Extended with `test_abidiff_parity_extended.py` (8 new cases):
- multi_fn_removed, var_removed, var_type_widened, pure_addition,
  param_count_changed, enum_member_added, virtual_dtor_added, elf_only_multi
**Remaining:** Expand to cover all 63 example cases via automated CI job.
**Effort for remaining:** 8h

#### 3. Real-World Library Regression Suite — DONE (synthetic pattern)
**Status:** Implemented in `test_realworld_scan.py` (6 tests):
- Realistic zlib-style API surface (structs, enums, typedefs, multiple functions)
- Compatible release (1.0→1.1): new function + enum member = COMPATIBLE
- Breaking release (1.0→2.0): struct layout change + func removed = BREAKING
- No-change (1.0→1.0): identical source = NO_CHANGE
- Cross-validation with abidiff on compatible release
**Remaining:** Download real library release tarballs for external validation.
**Effort for remaining:** 4h

---

### P1 — High Priority (Next sprint)

#### 4. Cross-Compiler False Positive Prevention — DONE
**Status:** Implemented in `test_cross_compiler_fp.py` (7 tests):
- gcc vs clang C compilation: no false positives
- g++ vs clang++ C++ compilation: documents known vtable DWARF divergence
- -O0 vs -O2 C/C++: no false positives from optimization differences
- debug vs stripped: graceful degradation, no BREAKING changes

#### 5. Compiler Flag Variation FP Tests — DONE
**Status:** Implemented in `test_cross_compiler_fp.py`:
- `-O0` vs `-O2` on both C and C++ → no BREAKING changes
- Debug vs `strip --strip-debug` → no BREAKING changes

#### 6. Transitive Dependency Chain Detection
**Gap:** Stack checker validates graphs but no test proves transitive ABI breaks.
**Risk:** libA re-exports libB symbols; libB breaks ABI; consumers of libA may not be warned.
**Plan:**
- Build 3-library chain: libC depends on libB depends on libA
- Break ABI in libA (middle layer)
- Assert stack-check propagates the break to libC consumers
**Effort:** 8h | **Requires:** cmake, gcc (integration marker)

#### 7. extern "C" Mixed Boundary Tests
**Gap:** `func_language_linkage_changed` is registered but no compiled integration test.
**Risk:** C++ libraries with C wrappers may have detection gaps.
**Plan:**
- Build C++ library with `extern "C"` wrapper functions
- Change C++ internals while preserving C API stability
- Assert C API is stable (NO_CHANGE) while C++ API may change
**Effort:** 4h | **Requires:** gcc (integration marker)

---

### P2 — Medium Priority (Backlog)

#### 8. Symbol Versioning Coexistence — DONE
**Status:** Implemented in `test_symbol_versioning_coexistence.py` (17 tests).
Covers version node add/remove, default vs non-default aliases, required versions,
combined version + symbol changes, and edge cases.

#### 9. Mutation Testing Integration — CONFIGURED
**Status:** `[tool.mutmut]` section added to `pyproject.toml`.
Targets 5 core modules: diff_symbols, diff_types, diff_platform, diff_filtering, checker_policy.
**Usage:** `mutmut run` → `mutmut results` → `mutmut show <id>`
**Remaining:** Run full mutation suite and add surviving mutant fixes to tests.
**Effort for remaining:** 4h

#### 10. Policy Override Matrix — DONE
**Status:** Implemented in `test_policy_override_matrix.py` (619 tests).
Covers exhaustive ChangeKind × policy matrix, sdk_vendor/plugin_abi downgrades,
PolicyFile overrides, and unknown policy fallback.

#### 11. Suppression Edge Cases — DONE
**Status:** Implemented in `test_suppression_edge_cases.py` (26 tests).
Covers expiration edge cases, pattern matching (regex/exact/type), conflicting rules,
audit trail integrity, and suppression + policy interaction.

#### 12. Parallel Safety — DONE
**Status:** Implemented in `test_parallel_safety.py` (6 tests).
Covers 10 concurrent independent comparisons, shared snapshot reads,
mixed change types concurrent, and sequential state independence.

---

### P3 — Low Priority (Nice to have)

#### 13. LTO Artifact FP Test
**Gap:** No test for symbols appearing/disappearing with `-flto`.
**Plan:** Compile with/without LTO; assert only expected symbol-level differences.
**Effort:** 4h

#### 14. Debug Info Version FP Test
**Gap:** Different DWARF versions (v4 vs v5) on identical source.
**Plan:** Compile with `-gdwarf-4` vs `-gdwarf-5`; assert no false positives.
**Effort:** 2h

#### 15. Windows MSVC DLL Integration
**Gap:** PE tests only use MinGW cross-compile; no real MSVC testing.
**Plan:** Add Windows CI with MSVC-compiled test DLLs.
**Effort:** 16h (requires Windows CI infrastructure)

#### 16. Real macOS dylib Tests
**Gap:** Mach-O `compat_version_changed` has minimal integration coverage.
**Plan:** Build dylibs on macOS CI with different compatibility versions.
**Effort:** 4h (requires macOS CI)

---

## ChangeKinds Depth Coverage Summary

### Fully Covered (10+ test references, dedicated scenarios)
All core ChangeKinds: `func_removed`, `func_added`, `func_return_changed`, `func_params_changed`,
`var_removed`, `var_type_changed`, `type_size_changed`, `type_field_removed`, `enum_member_removed`,
`enum_member_value_changed`, `typedef_removed`, `soname_changed`, etc.

### Now Deeply Covered (via new test files)
These had only 1-3 references before and now have dedicated detection tests:
- `func_static_changed`, `func_cv_changed`, `func_visibility_protected_changed`
- `func_virtual_added/removed`, `func_pure_virtual_added`, `func_virtual_became_pure`
- `func_noexcept_removed`, `func_deleted`, `func_ref_qual_changed`
- `func_language_linkage_changed`, `func_became_inline`, `func_lost_inline`
- `union_field_added/removed/type_changed`
- `field_became_const/volatile/mutable`, `field_lost_const/volatile/mutable`
- `field_bitfield_changed`, `field_renamed`, `enum_member_renamed`
- `type_became_opaque`, `type_alignment_changed`, `base_class_position_changed`
- `symbol_binding_changed/strengthened`, `symbol_type_changed`, `symbol_size_changed`
- `ifunc_introduced/removed`, `elf_visibility_changed`
- `executable_stack`, `rpath_changed`, `runpath_changed`
- `struct_size_changed`, `struct_field_offset_changed`, `struct_field_removed/type_changed`
- `struct_alignment_changed`, `enum_underlying_size_changed`, `dwarf_info_missing`
- `calling_convention_changed`, `struct_packing_changed`, `toolchain_flag_drift`
- `value_abi_trait_changed`, `frame_register_changed`
- `param_pointer_level_changed`, `return_pointer_level_changed`
- `param_restrict_changed`, `param_became/lost_va_list`
- `param_default_value_changed/removed`, `param_renamed`
- `var_value_changed`, `var_access_changed/widened`, `var_became/lost_const`
- `constant_changed/added/removed`

### Still Shallow (require real binary integration tests)
- `func_removed_from_binary` — registered but no detector emits it yet
- `symbol_renamed_batch` — tested but needs real library rename scenarios
- `func_likely_renamed` — tested in elf_only_mode; needs compiled binary validation
- `glibcxx_dual_abi_flip_detected` — tested but FP rate unknown
- `abi_surface_explosion` — threshold heuristics untested with real data
- `vtable_symbol_identity_changed` — requires compiled C++ binaries with RTTI
- `inline_namespace_moved` — requires compiled C++ binaries with inline namespaces
- `sycl_*` (8 kinds) — synthetic tests exist; need real SYCL binaries

---

## Architecture Notes

### Test Organization Strategy
```text
tests/
├── test_checker.py                  # Core compare() + verdict classification
├── test_scan_accuracy.py            # Mutation-based FP/FN prevention
├── test_negative.py                 # Benign changes NOT flagged
├── test_bidirectional_symmetry.py   # NEW: v1<->v2 symmetric detection
├── test_diff_symbols_deep.py        # NEW: Deep symbol detector coverage
├── test_diff_types_deep.py          # NEW: Deep type detector coverage
├── test_diff_platform_deep.py       # NEW: Deep platform detector coverage
├── test_multi_detector_interaction.py # NEW: Cross-detector dedup
├── test_confidence_evidence.py      # NEW: Evidence tier assertions
├── test_false_positive_resistance.py # NEW: Systematic FP prevention
├── test_example_autodiscovery.py    # Integration: compiled example cases
├── test_property_based.py           # Hypothesis fuzzing
└── ...
```

### Naming Conventions
- `test_*_deep.py` — Deep coverage for ChangeKinds with previously shallow references
- `test_*_interaction.py` — Cross-cutting concern tests
- `test_*_resistance.py` — False positive/negative prevention tests

### Fixture Patterns
- `_snap()` — Minimal AbiSnapshot factory
- `_pub_func()` — Public function factory
- `_pub_var()` — Public variable factory
- `_kinds(result)` — Extract ChangeKind set from DiffResult
- `_all_kinds(result)` — Include redundant changes in kind set
