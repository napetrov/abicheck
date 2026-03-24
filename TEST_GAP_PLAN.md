# Test Gap Plan — Scanner Accuracy & Coverage Enhancement

## Current State (Post Enhancement)

- **139 existing test files** + **7 new test files** = 146 test files
- **4,516 existing tests** + **196 new tests** = 4,712 total
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

---

## Remaining Gaps — Prioritized

### P0 — Critical (Should block next release)

#### 1. Stripped Binary Graceful Degradation
**Gap:** No test validates behavior when DWARF debug info is absent (`strip -g`).
**Risk:** Scanner may crash or produce misleading results on production binaries.
**Plan:**
- Add integration test that compiles a library, strips it, and runs comparison
- Assert lower confidence level (LOW) and no crashes
- Assert `DWARF_INFO_MISSING` change is reported
- Verify header-only analysis still detects symbol-level changes
**Effort:** 4h | **Requires:** gcc/castxml (integration marker)

#### 2. Differential Testing vs abidiff on Compiled Binaries
**Gap:** Parity tests use synthetic snapshots, not actual compiled binaries.
**Risk:** Real-world false negatives that synthetic tests can't catch.
**Plan:**
- For each example case (01-62), run both abicheck and `abidiff`
- Compare detected change sets; document intentional divergences
- Add CI job gated on `@pytest.mark.libabigail`
**Effort:** 16h | **Requires:** abidiff, gcc, cmake

#### 3. Real-World Library Regression Suite
**Gap:** Only libz demo exists for e2e. No comparison of actual library releases.
**Risk:** Scanner may fail on complex real-world symbol tables.
**Plan:**
- Download 2-3 known library release pairs (e.g., zstd 1.5.5 vs 1.5.6, libpng 1.6.43 vs 1.6.44)
- Validate against known changelogs / release notes
- Add as `@pytest.mark.slow` integration tests
**Effort:** 8h

---

### P1 — High Priority (Next sprint)

#### 4. Cross-Compiler False Positive Prevention
**Gap:** No test confirming same source compiled with gcc vs clang produces no spurious diffs.
**Risk:** Different debug info producers may cause false positives.
**Plan:**
- Compile same test case with both gcc and clang
- Compare resulting snapshots; assert NO_CHANGE or COMPATIBLE only
- Add `toolchain_flag_drift` as expected (informational, not breaking)
**Effort:** 8h | **Requires:** gcc, clang (integration marker)

#### 5. Compiler Flag Variation FP Tests
**Gap:** No test for different `-O`/`-g`/`-fsanitize=` flags on identical source.
**Risk:** Optimization level changes may cause false positives.
**Plan:**
- Compile same source with `-O0` vs `-O2`, `-g` vs no `-g`
- Assert no BREAKING changes from optimization differences
- Test that sanitizer hooks (`__asan_*`) don't trigger false positives
**Effort:** 4h | **Requires:** gcc (integration marker)

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

#### 8. Symbol Versioning Coexistence
**Gap:** No test for libraries providing both `foo@V1` and `foo@@V2` (glibc pattern).
**Plan:** Create ELF metadata with multiple version aliases; verify correct detection.
**Effort:** 4h

#### 9. Mutation Testing Integration
**Gap:** No mutation testing to verify tests catch regressions in detector logic.
**Plan:** Add `mutmut` config targeting `diff_symbols.py`, `diff_types.py`, `diff_platform.py`.
**Effort:** 8h

#### 10. Policy Override Matrix
**Gap:** No systematic test of all 143 ChangeKind x 3 policy combinations.
**Plan:** Generate matrix test asserting each override produces expected verdict.
**Effort:** 4h

#### 11. Suppression Edge Cases
**Gap:** No test for conflicting rules, policy+suppression interaction, timezone-aware expiration.
**Plan:** Add dedicated `test_suppression_edge_cases.py` with conflict resolution tests.
**Effort:** 4h

#### 12. Parallel Safety
**Gap:** No test validates concurrent `compare()` calls don't interfere.
**Plan:** ThreadPoolExecutor running 10 concurrent comparisons with shared/different snapshots.
**Effort:** 2h

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
- `vtable_symbol_identity_changed` — needs compiled C++ with RTTI
- `inline_namespace_moved` — needs compiled C++ with inline namespaces
- `sycl_*` (8 kinds) — synthetic tests exist; need real SYCL binaries

---

## Architecture Notes

### Test Organization Strategy
```
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
