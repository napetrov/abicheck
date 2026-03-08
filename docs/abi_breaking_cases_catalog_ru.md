# ABI Breaking Cases Catalog (v1)

Below is a structured catalog of cases from `examples/case01..case18` for studying
**ABI backward-compatibility breakage** scenarios.

## 1) Symbol/API surface breaks

1. **case01_symbol_removal** — removal of a public symbol from `.so`.
   - Risk: runtime loader error / undefined symbol.
   - Type: hard break.

2. **case02_param_type_change** — function parameter type changed.
   - Risk: ABI mismatch in calling convention/register usage.
   - Type: hard break.

3. **case10_return_type** — function return type changed.
   - Risk: truncation / UB on the consumer side.
   - Type: hard break.

4. **case12_function_removed** — function disappears (for example after inline refactor).
   - Risk: unresolved symbol for old binaries.
   - Type: hard break.

## 2) Type/layout breaks

5. **case07_struct_layout** — struct layout changed (field add/reorder/offset shift).
   - Risk: size/offset mismatch, memory corruption.
   - Type: hard break.

6. **case08_enum_value_change** — enum values reordered/inserted.
   - Risk: semantic incompatibility (wrong branch/mode selection).
   - Type: semantic ABI break.

7. **case11_global_var_type** — global variable type changed.
   - Risk: size/alignment mismatch.
   - Type: hard break.

8. **case17_template_abi** — layout/ABI changed for instantiated template type.
   - Risk: binary mismatch between translation units, ODR/size mismatch.
   - Type: hard break.

9. **case18_dependency_leak** — ABI dependency leak through public headers.
   - Risk: external dependency upgrade breaks ABI with no changes in our `.so`.
   - Type: transitive ABI break.

## 3) C++ ABI-specific breaks

10. **case09_cpp_vtable** — virtual method set/order changed (vtable drift).
    - Risk: wrong virtual method call target.
    - Type: hard break.

11. **case14_cpp_class_size** — class size changed.
    - Risk: new/delete mismatch, object layout corruption.
    - Type: hard break.

12. **case15_noexcept_change** — `noexcept` removed/changed.
    - Risk: exception contract change, ABI/behavior mismatch.
    - Type: semantic break (often poorly detected by ELF-only tools).

13. **case16_inline_to_non_inline** — inline→non-inline (or reverse) with ODR effects.
    - Risk: multiple definitions, mixed TU behavior.
    - Type: ODR/semantic ABI risk.

## 4) ELF/linker/policy cases (important for release policy)

14. **case05_soname** — missing/incorrect SONAME.
    - Risk: uncontrolled ABI substitution on upgrade.
    - Type: policy break.

15. **case06_visibility** — internal symbols leaked as exports.
    - Risk: accidental public ABI surface, future lock-in.
    - Type: ABI hygiene break.

16. **case13_symbol_versioning** — missing symbol versioning.
    - Risk: harder compatibility control across releases/distributions.
    - Type: policy/tooling break.

## 5) Control cases (not direct ABI breaks)

17. **case03_compat_addition** — compatible symbol addition.
18. **case04_no_change** — unchanged baseline.

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
