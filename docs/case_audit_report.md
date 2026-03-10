# ABI Example Case Audit Report

**Generated:** 2026-03-10  
**Audited on:** onedal-build (Ubuntu, 8 vCPU / 32GB)  
**Cases:** case01–case41 in `~/abi-check/examples/`  
**Method:** Build each case → run app with `LD_PRELOAD=libv2.so` → run `abicheck dump+compare`

---

## Summary Table

| Case | Name | README Verdict | abicheck Verdict | Runtime Result | Status |
|------|------|---------------|-----------------|----------------|--------|
| case01 | symbol_removal | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (no crash) | ⚠️ App gap |
| case02 | param_type_change | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (wrong output) | ✅ OK |
| case03 | compat_addition | 🟢 COMPATIBLE | ✅ COMPATIBLE | EXIT:0 | ✅ OK |
| case04 | no_change | ✅ NO_CHANGE | ✅ NO_CHANGE | EXIT:0 | ✅ OK |
| case05 | soname | 🟡 BAD PRACTICE | ✅ NO_CHANGE | EXIT:0 | ℹ️ Known gap |
| case06 | visibility | 🟡 BAD PRACTICE | ❌ BREAKING | EXIT:1 (libbad.so missing) | ❌ App broken |
| case07 | struct_layout | 🟡 ABI CHANGE | ❌ BREAKING | EXIT:134 (stack smash) | ✅ OK |
| case08 | enum_value_change | 🟡 ABI CHANGE | ❌ BREAKING | EXIT:0 (wrong output) | ✅ OK |
| case09 | cpp_vtable | 🟡 ABI CHANGE | ❌ BREAKING | EXIT:0 (wrong dispatch) | ✅ OK |
| case10 | return_type | 🟡 ABI CHANGE | ❌ BREAKING | EXIT:0 (truncated value) | ✅ OK |
| case11 | global_var_type | 🟡 ABI CHANGE | ❌ BREAKING | EXIT:0 (linker warning+truncation) | ✅ OK |
| case12 | function_removed | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (no crash) | ⚠️ App gap |
| case13 | symbol_versioning | 🔴 BREAKING | ✅ COMPATIBLE | EXIT:0 | ❌ Detection gap |
| case14 | cpp_class_size | 🟡 ABI CHANGE | ❌ BREAKING | EXIT:134 (stack smash) | ✅ OK |
| case15 | noexcept_change | 🔴 BREAKING | ❌ BREAKING | EXIT:134 (terminate) | ✅ OK |
| case16 | inline_to_non_inline | 🟢 COMPATIBLE | ✅ COMPATIBLE | EXIT:0 | ✅ OK |
| case17 | template_abi | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (heap corruption) | ✅ OK |
| case18 | dependency_leak | 🟡 SOURCE_BREAK* | ❌ BREAKING | EXIT:0 (boundary corruption) | ✅ OK |
| case19 | enum_member_removed | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (value used directly) | ✅ OK† |
| case20 | enum_member_value_changed | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (wrong output) | ✅ OK |
| case21 | method_became_static | 🟢 COMPATIBLE | ✅ NO_CHANGE | EXIT:0 | ✅ OK |
| case22 | method_const_changed | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (no crash) | ⚠️ App gap |
| case23 | pure_virtual_added | 🔴 BREAKING | ❌ BREAKING | EXIT:134 (abort) | ✅ OK |
| case24 | union_field_removed | 🔴 BREAKING | ❌ BREAKING | EXIT:2 (explicit check) | ✅ OK |
| case25 | enum_member_added | 🟢 COMPATIBLE | ✅ NO_CHANGE | EXIT:0 | ℹ️ Header-only |
| case26 | union_field_added | 🔴 BREAKING | ❌ BREAKING | EXIT:134 (stack smash) | ✅ OK |
| case27 | symbol_binding_weakened | 🟢 COMPATIBLE | ✅ COMPATIBLE | EXIT:0 | ✅ OK |
| case28 | typedef_opaque | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (detailed demo) | ✅ OK |
| case29 | ifunc_transition | 🟢 COMPATIBLE | ✅ COMPATIBLE | EXIT:0 | ✅ OK |
| case30 | field_qualifiers | 🟡 SOURCE_BREAK | ✅ NO_CHANGE | EXIT:0 | ℹ️ Correct |
| case31 | enum_rename | 🟡 SOURCE_BREAK | ⚠️ SOURCE_BREAK | EXIT:0 | ✅ OK |
| case32 | param_defaults | ✅ NO_CHANGE | ✅ NO_CHANGE | EXIT:0 | ✅ OK |
| case33 | pointer_level | 🔴 BREAKING | ❌ BREAKING | EXIT:139 (segfault) | ✅ OK |
| case34 | access_level | 🟡 SOURCE_BREAK | ✅ NO_CHANGE | EXIT:0 | ℹ️ Correct |
| case35 | field_rename | 🟡 SOURCE_BREAK | ✅ NO_CHANGE | EXIT:0 | ℹ️ Correct |
| case36 | anon_struct | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (layout corruption) | ✅ OK |
| case37 | base_class | 🔴 BREAKING | ✅ NO_CHANGE | EXIT:139 (segfault) | ❌ Detection gap |
| case38 | virtual_methods | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (no crash) | ⚠️ App gap |
| case39 | var_const | 🔴 BREAKING | ✅ NO_CHANGE | EXIT:0 | ❌ Detection gap |
| case40 | field_layout | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (wrong output) | ✅ OK |
| case41 | type_changes | 🔴 BREAKING | ❌ BREAKING | EXIT:0 (partial gap) | ⚠️ App gap |

*case18 README describes it as SOURCE_BREAK in header but the runtime clearly shows ABI-level corruption; abicheck correctly returns BREAKING.  
†case19 runtime works because the baked-in integer value still exists; the break manifests only when the new .so reinterprets enum semantics.

**Legend:** ✅ OK = correct behavior; ⚠️ App gap = runtime doesn't exercise breaking path; ❌ Detection gap = abicheck misses real break; ℹ️ = expected/known limitation.

---

## Cases Needing Attention

### ❌ Critical: abicheck Detection Gaps

#### case13_symbol_versioning
- **README:** 🔴 BREAKING — switching from `LIBFOO_1.0` versioned symbol to unversioned `foo` breaks any binary linked against the versioned symbol.
- **abicheck:** ✅ COMPATIBLE — reports only a "compatible addition" of `LIBFOO_1.0` (treats the new unversioned symbol as an addition, misses the removal of the versioned binding).
- **Runtime:** EXIT:0 — works in `LD_PRELOAD` test (LD_PRELOAD doesn't respect symbol version binding the same way direct linking does).
- **Issue:** abicheck does not check `GNU_VERSION_R` (`DT_VERNEEDED`) changes or version node removals. Symbol versioning breaks (removing a specific `LIBFOO_1.0@` binding) are not detected.
- **Fix needed:** Add symbol version binding change detection to `abicheck.cli compare`. When a versioned symbol disappears and is replaced with an unversioned one, this should be BREAKING.

#### case37_base_class
- **README:** 🔴 BREAKING — adding a data member to a base class shifts all derived class fields, breaking sizeof/offset assumptions of pre-compiled derived classes.
- **abicheck:** ✅ NO_CHANGE — reports no ABI changes at all.
- **Runtime:** EXIT:139 (segfault) — binary crashes, confirming real break.
- **Issue:** abicheck cannot see base class type information from the `.so` alone (no DWARF type info for the base class in this case). The `struct_size_changed` checker only fires when the type appears directly in exported function signatures.
- **Fix needed:** Ensure C++ class hierarchy changes (base class field additions) are detected. Requires DWARF analysis of inherited types via `-H` header or DWARF debug info in the shared library.

#### case39_var_const
- **README:** 🔴 BREAKING (runtime write to const global) / Note that README also says "NO_CHANGE in headers-only abicheck" — this is a known dual classification.
- **abicheck:** ✅ NO_CHANGE — `const` qualification change on exported global variables is not detected.
- **Runtime:** EXIT:0 — no crash (writing a "const" global still works at machine-code level; the break is UB).
- **Issue:** `const` qualifier on global variables is not encoded in the ELF symbol table (no type info for globals without DWARF). Without `-H` providing the header, abicheck can't detect this change.
- **Fix needed (if applicable):** If the `dump` command is run with `-H v2.h`, check if `const` qualifier change on `lib_version_str` is detectable. If so, document that `-H` is required for qualifier checks on globals. Consider adding a note to the README that this is a "source ABI break" best detected at source level.

---

### ⚠️ App Runtime Doesn't Exercise Breaking Path

The following cases claim BREAKING in README but the `LD_PRELOAD` runtime test exits 0 without errors. The reason in all cases is that `libv1.so` is still present in the case directory and linked via `-rpath .` in the app binary. When `LD_PRELOAD=./libv2.so` is applied, the dynamic linker finds the missing symbol in `libv1.so` as a fallback, masking the break.

#### case01_symbol_removal
- **Expected:** `undefined symbol: helper` crash on startup.
- **Actual:** `helper(5) = 6` — still found in `libv1.so` via rpath.
- **Fix:** Remove or rename `libv1.so` before running the LD_PRELOAD test, or build the app with `-rpath` pointing only to the LD_PRELOAD target. Alternatively, use `LD_LIBRARY_PATH=. ./app_v1` after replacing `libv1.so` with `libv2.so` (as the README's own "Real Failure Demo" shows).

#### case12_function_removed  
- **Expected:** `undefined symbol: fast_add` crash.
- **Actual:** `fast_add(3, 4) = 7` — still found in `libv1.so`.
- **Fix:** Same as case01 — replace `libv1.so` with `libv2.so` for the runtime test instead of using LD_PRELOAD alongside the original.

#### case22_method_const_changed
- **Expected:** Symbol `_ZNK6Widget3getEv` (const version) not found in v2, causing link/runtime error.
- **Actual:** `get() const called` EXIT:0 — const version still in `libv1.so`.
- **Fix:** Same as above — runtime test must eliminate `libv1.so` from the resolution path.

#### case38_virtual_methods
- **Expected:** Virtual call via stale vtable causes crash or wrong dispatch.
- **Actual:** EXIT:0, all calls succeed — app uses `MyProcessor` subclass which overrides `execute()` and doesn't rely on `Processor::execute()` from the library.
- **Fix:** The app should call `Processor::execute()` directly (or via a base pointer that is NOT overridden in the test consumer) to demonstrate the breaking change. The subclass override masks the break.

#### case41_type_changes
- **Expected:** `process_config()` missing in v2 causes runtime failure.
- **Actual:** EXIT:0, `process_config(mode=1, flags=255)` printed — still found in `libv1.so`.
- **Fix:** Same as case01/case12 — eliminate `libv1.so` from resolution path in runtime test.

---

### ❌ App Infrastructure Broken

#### case06_visibility
- **Runtime error:** `dlopen libbad.so: ./libbad.so: cannot open shared object file: No such file or directory` EXIT:1.
- **Issue:** The app tries to `dlopen("./libbad.so")` which doesn't exist in the case directory. The build produces `libv1.so`/`libv2.so` but not `libbad.so`.
- **Fix:** Either rename `libv1.so` → `libbad.so` in the Makefile/app, or update the app to dlopen `./libv1.so`. The visibility scenario itself (internal symbols becoming public/private) is correctly detected by abicheck as BREAKING (2 removed ELF-only functions).

---

### ℹ️ Known Limitations (Not Bugs, Worth Documenting)

#### case05_soname
- SONAME change is an ELF-level break but not an ABI symbol change. abicheck correctly says NO_CHANGE.
- README verdict "BAD PRACTICE" is appropriate but not a standard abicheck verdict category.
- **Recommendation:** Add explicit documentation that SONAME changes are outside abicheck's scope.

#### case25_enum_member_added
- abicheck reports NO_CHANGE despite README saying COMPATIBLE (enum member added).
- Reason: C enum values are compile-time constants embedded in object code, not exported as ELF symbols. The `.so` has no trace of the new `VIOLET` member.
- **Recommendation:** README should note that header-only enum additions are invisible to binary-level ABI tools.

#### case30_field_qualifiers, case34_access_level, case35_field_rename
- These are source-level (semantic) breaks with no binary ABI change. abicheck correctly returns NO_CHANGE.
- Without `-H` header files, abicheck cannot detect these.
- **Recommendation:** Add note that source-level breaks require header-aware analysis (use `-H`).

---

## Summary of Issues to Fix

### P0 — Detection Gaps (abicheck misses real breaks)
1. **case13**: Symbol version binding removal → should be BREAKING, abicheck says COMPATIBLE
2. **case37**: C++ base class field addition → should be BREAKING, abicheck says NO_CHANGE

### P1 — abicheck Limitation (by design, needs documentation)
3. **case39**: `const` qualifier change on global variable → needs `-H` to detect; README should clarify

### P2 — App Test Gaps (LD_PRELOAD test invalid, breaking path not exercised)
4. **case01**: `helper()` still resolved from libv1.so — LD_PRELOAD doesn't isolate
5. **case12**: `fast_add()` still resolved from libv1.so
6. **case22**: `_ZNK6Widget3getEv` still resolved from libv1.so
7. **case38**: Subclass overrides mask vtable break
8. **case41**: `process_config()` still resolved from libv1.so

### P3 — App Infrastructure Broken
9. **case06**: App tries to `dlopen("./libbad.so")` which doesn't exist

### P4 — Documentation/README Issues
10. **case04, case05, case06, case07, case08, case09, case10, case11, case14, case18**: README uses non-standard verdict formats (BAD PRACTICE, ABI CHANGE, SOURCE_BREAK) — inconsistent with BREAKING/COMPATIBLE/SOURCE_BREAK/NO_CHANGE taxonomy used in abicheck output.
11. **case25, case30, case34, case35**: README could better explain why abicheck says NO_CHANGE (expected behavior).

---

## Statistics

| Category | Count |
|----------|-------|
| Fully correct (✅) | 22 |
| App gap (⚠️) | 5 |
| abicheck detection gap (❌) | 3 |
| App infrastructure broken (❌) | 1 |
| Known limitation / informational (ℹ️) | 4 |
| Inconsistent README verdict format | 10 |
| **Total cases** | **41** |

---

## Per-Case abicheck Output Reference

All abicheck runs used:
```bash
python3 -m abicheck.cli dump <libX.so> [-H <vX.h>] -o /tmp/vX.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
```

Exit codes: 0=NO_CHANGE/COMPATIBLE, 2=SOURCE_BREAK, 4=BREAKING.

Full raw results are in `/tmp/audit_results.txt` on onedal-build.
