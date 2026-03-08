# ABI Breaking Cases Catalog (v1)

This catalog summarizes breakage patterns covered by `examples/case01..case24`.
For full code walkthroughs and deep per-case narrative, see
[`docs/examples_breakage_guide.md`](examples_breakage_guide.md).

## 1) Symbol/API surface breaks

1. **case01_symbol_removal** — removal of a public symbol from `.so`.
   - Risk: runtime loader error / undefined symbol.
   - Type: hard break.
   - Example: `examples/case01_symbol_removal/`
   - Mitigation: keep compatibility wrappers and remove only in a major ABI line.

2. **case02_param_type_change** — function parameter type changed.
   - Risk: ABI mismatch in calling convention/register usage.
   - Type: hard break.
   - Example: `examples/case02_param_type_change/`
   - Mitigation: preserve old symbol and add a versioned API entry point.

3. **case10_return_type** — function return type changed.
   - Risk: truncation / UB on the consumer side.
   - Type: hard break.
   - Example: `examples/case10_return_type/`
   - Mitigation: keep old return-type function, add `*_v2` with new contract.

4. **case12_function_removed** — function disappears (for example after refactor).
   - Risk: unresolved symbol for old binaries.
   - Type: hard break.
   - Example: `examples/case12_function_removed/`
   - Mitigation: deprecate first and remove only with SONAME-major transition.

## 2) Type/layout breaks

5. **case07_struct_layout** — struct layout changed (field add/reorder/offset shift).
   - Risk: size/offset mismatch, memory corruption.
   - Type: hard break.
   - Example: `examples/case07_struct_layout/`
   - Mitigation: use opaque handles/Pimpl; avoid in-place public struct mutation.

6. **case08_enum_value_change** — enum values reordered/inserted.
   - Risk: semantic incompatibility (wrong branch/mode selection).
   - Type: semantic ABI break.
   - Example: `examples/case08_enum_value_change/`
   - Mitigation: treat released enum numeric values as immutable.

7. **case11_global_var_type** — global variable type changed.
   - Risk: size/alignment mismatch.
   - Type: hard break.
   - Example: `examples/case11_global_var_type/`
   - Mitigation: avoid mutable exported globals; use accessor APIs.

8. **case17_template_abi** — layout/ABI changed for instantiated template type.
   - Risk: binary mismatch between translation units, ODR/size mismatch.
   - Type: hard break.
   - Example: `examples/case17_template_abi/`
   - Mitigation: keep unstable templates out of ABI boundary.

9. **case18_dependency_leak** — ABI dependency leak through public headers.
   - Risk: external dependency upgrade breaks ABI with no changes in our `.so`.
   - Type: transitive ABI break.
   - Example: `examples/case18_dependency_leak/`
   - Mitigation: do not expose third-party layout types in public headers.

10. **case24_union_field_removed** — union member removed from public type.
    - Risk: representation contract shrink; old consumers may read/write invalid variant.
    - Type: semantic + layout contract break.
    - Example: `examples/case24_union_field_removed/`
    - Mitigation: keep union variants stable or introduce versioned replacement type.

## 3) C++ ABI-specific breaks

11. **case09_cpp_vtable** — virtual method set/order changed (vtable drift).
    - Risk: wrong virtual method call target.
    - Type: hard break.
    - Example: `examples/case09_cpp_vtable/`
    - Mitigation: freeze vtable contract or version interfaces (`I2`).

12. **case14_cpp_class_size** — class size changed.
    - Risk: new/delete mismatch, object layout corruption.
    - Type: hard break.
    - Example: `examples/case14_cpp_class_size/`
    - Mitigation: use Pimpl to stabilize externally visible object layout.

13. **case15_noexcept_change** — `noexcept` removed/changed.
    - Risk: source-level contract change; does NOT change Itanium ABI mangled name.
    - Type: **compatible/warning** (not a binary ABI break — same symbol resolves).
    - Verdict: COMPATIBLE.
    - Example: `examples/case15_noexcept_change/`
    - Mitigation: treat `noexcept` as stable public contract for source compatibility.

14. **case16_inline_to_non_inline** — inline→non-inline (or reverse) with ODR effects.
    - Risk: multiple definitions, mixed TU behavior.
    - Type: ODR/semantic ABI risk.
    - Example: `examples/case16_inline_to_non_inline/`
    - Mitigation: keep inline strategy stable for public headers.

15. **case21_method_became_static** — member method changed to static.
    - Risk: changed call/mangling ABI for existing callers.
    - Type: hard break.
    - Example: `examples/case21_method_became_static/`
    - Mitigation: keep original member method, add static helper under new name.

16. **case22_method_const_changed** — method const-qualification changed.
    - Risk: mangled symbol identity and overload contract changed.
    - Type: hard break.
    - Example: `examples/case22_method_const_changed/`
    - Mitigation: preserve old signature, add new API variant.

17. **case23_pure_virtual_added** — pure virtual method added.
    - Risk: existing implementations become incompatible with expanded interface.
    - Type: hard break.
    - Example: `examples/case23_pure_virtual_added/`
    - Mitigation: introduce interface v2 and keep old interface frozen.

## 4) ELF/linker/policy cases (important for release policy)

18. **case05_soname** — missing/incorrect SONAME.
    - Risk: uncontrolled ABI substitution on upgrade.
    - Type: policy break.
    - Example: `examples/case05_soname/`
    - Mitigation: bump SONAME on incompatible ABI changes.

19. **case06_visibility** — internal symbols leaked as exports.
    - Risk: accidental public ABI surface, future lock-in.
    - Type: ABI hygiene break.
    - Example: `examples/case06_visibility/`
    - Mitigation: default hidden visibility and explicit export macros.

20. **case13_symbol_versioning** — missing symbol versioning.
    - Risk: harder compatibility control across releases/distributions.
    - Type: policy/tooling break.
    - Example: `examples/case13_symbol_versioning/`
    - Mitigation: maintain and test symbol version scripts in CI.

## 5) Control cases (not direct ABI breaks)

21. **case03_compat_addition** — compatible symbol addition.
22. **case04_no_change** — unchanged baseline.

## 6) Additional enum compatibility cases

23. **case19_enum_member_removed** — enum member removed.
    - Risk: old persisted/protocol values become invalid or semantically undefined.
    - Type: semantic compatibility break.
    - Example: `examples/case19_enum_member_removed/`
    - Mitigation: keep old enum members; mark deprecated instead of deleting.

24. **case20_enum_member_value_changed** — enum member numeric value changed.
    - Risk: cross-version state/wire interpretation mismatch.
    - Type: semantic compatibility break.
    - Example: `examples/case20_enum_member_value_changed/`
    - Mitigation: never renumber released enum constants.

## 7) Additional detected changes and verdicts

Beyond the core symbol/type/C++ checks above, abicheck detects a number of
ELF-metadata, DWARF-diagnostic, and qualifier changes. Each is classified
according to whether it causes a proven binary-level failure.

### Compatible/warning changes

These are detected and reported but do **not** trigger a BREAKING verdict
because they do not cause binary linkage or layout failures on their own.

25. **noexcept added/removed** — `noexcept` specifier changed on a function.
    - Itanium ABI mangling does not change in practice — the same symbol resolves.
    - Source-level concern only (C++17 function-pointer type mismatch).
    - Verdict: COMPATIBLE.

26. **Enum member added** — new enumerator appended to an existing enum.
    - Existing compiled enum values are unchanged.
    - Source-level concern (switch statement coverage).
    - Value shifts (if any) are caught separately by `ENUM_MEMBER_VALUE_CHANGED`.
    - Verdict: COMPATIBLE.

27. **Union field added** — new field added to an existing union.
    - All union fields share offset 0; existing fields are unaffected.
    - Size increase (if any) is caught separately by `TYPE_SIZE_CHANGED`.
    - Verdict: COMPATIBLE.

28. **GLOBAL→WEAK symbol binding** — symbol weakened from `STB_GLOBAL` to `STB_WEAK`.
    - Symbol is still exported and resolvable by the dynamic linker.
    - Interposition semantics change but existing binaries continue to work.
    - Verdict: COMPATIBLE.

29. **GNU IFUNC introduced/removed** — symbol changed to/from `STT_GNU_IFUNC`.
    - Transparent to callers; PLT/GOT mechanism handles indirect resolution.
    - This is an implementation optimization, not an ABI contract change.
    - Verdict: COMPATIBLE.

30. **New/removed DT_NEEDED dependency** — library gained or dropped a shared library dependency.
    - Deployment/packaging concern; does not affect the library's exported symbol contract.
    - Verdict: COMPATIBLE.

31. **RPATH/RUNPATH changed** — library search path metadata changed.
    - Operational concern; no effect on symbol contract or type layout.
    - Verdict: COMPATIBLE.

32. **Toolchain flag drift** — different compiler flags detected via `DW_AT_producer`.
    - Informational diagnostic; not a proven binary break on its own.
    - Verdict: COMPATIBLE.

33. **DWARF info missing** — new binary lacks debug info.
    - Coverage gap warning: struct/enum layout comparison was skipped.
    - Not a break; indicates the comparison is incomplete.
    - Verdict: COMPATIBLE.

### Borderline changes classified as BREAKING

These changes are less obvious than a removed symbol or shifted struct layout,
but they can cause hard runtime failures in realistic deployments.

34. **ELF st_size changed** — symbol size metadata changed in `.dynsym`.
    - `st_size` is informational metadata; the dynamic linker does not use it for resolution.
    - However, in ELF-only mode (no headers/DWARF) it may be the **sole** signal for
      vtable growth or variable type changes.
    - Verdict: **BREAKING** (to avoid false negatives in stripped-binary workflows).

35. **New dependency version requirement** — library now requires e.g. `GLIBC_2.34`.
    - Library fails to load on runtimes lacking the required version.
    - Verdict: **BREAKING** (hard runtime failure on affected systems).

36. **Typeinfo/vtable visibility changed** — visibility attribute changed on type metadata.
    - Cross-DSO `dynamic_cast` and C++ exception matching can fail at runtime.
    - Verdict: **BREAKING**.

37. **Variable const qualifier added/removed** — global variable gained or lost `const`.
    - Adding `const` moves variable to `.rodata`; existing writes cause SIGSEGV.
    - Removing `const` is an ODR / inlining break (callers may have cached the value).
    - Verdict: **BREAKING**.

---

## Candidate additions for v2

1. **Calling convention drift** (`cdecl`/`stdcall`, SysV vs vectorcall).
2. **Alignment/packing changes** (`#pragma pack`, `alignas`).
3. **Bit-field layout changes** (compiler/version/flags dependent).
4. **Exception type ABI changes** (throw spec + RTTI interplay).
5. **Allocator ABI changes** (`std::pmr`, custom allocator hooks).
6. **STL ABI toggles** (`_GLIBCXX_USE_CXX11_ABI`, libc++/libstdc++ mixing).
7. **Cross-compiler ABI drift** (GCC vs Clang vs MSVC for same headers).
8. **LTO/visibility interaction** (inlined symbol disappearance with LTO).
9. **IFUNC / CPU dispatch symbol changes**.
10. **Weak symbol semantic changes**.
