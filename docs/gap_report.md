# ABI Checker Gap Analysis — abicheck vs ABICC vs libabigail

> Generated: 2026-03-07  
> abicheck version: HEAD of `napetrov/abicheck`  
> Compared against: ABICC (lvc/abi-compliance-checker) + libabigail (abidiff/abidw)

---

## Summary

- **abicheck covers:** ~43/49 de-duplicated ABI break scenarios (~88%) after Sprint 1-6
- **Key differentiator:** abicheck uses multi-tier analysis (castxml headers + ELF symbols + DWARF layout) -- works on **release builds** with headers + `.so`, no debug symbols required for core checks. ABICC needs GCC `-fdump-lang-spec`, abidiff needs DWARF debug info.
- **Closed gaps (Sprint 1-6):** All 10 original P0 cases are now detected; ELF-only layer, DWARF layout, advanced DWARF (calling convention, packing, toolchain flags), ABICC compat CLI, and libabigail parity tests added.
- **Coverage ceiling:** ~88% with the multi-tier architecture (remaining gaps are mostly P2 items)

> Note: ABICC has 90+ rules total, but many are sub-rules of the same scenario. The 49-row coverage table below is the de-duplicated scenario count used for all % calculations.
>
> **Sprint status:** Sprint 1 (core detectors), Sprint 2 (ELF-only), Sprint 3 (DWARF layout), Sprint 4 (advanced DWARF), Sprint 5 (ABICC compat), Sprint 6 (libabigail parity) -- all implemented.

---

## What abicheck ALREADY covers

| Case | abicheck | ABICC | abidiff | Notes |
|------|----------|-------|---------|-------|
| Function removed | ✅ `FUNC_REMOVED` | ✅ | ✅ | Via readelf symtab |
| Function added | ✅ `FUNC_ADDED` | ✅ | ✅ | |
| Return type changed | ✅ `FUNC_RETURN_CHANGED` | ✅ | ✅ | |
| Parameter type changed | ✅ `FUNC_PARAMS_CHANGED` | ✅ | ✅ | |
| noexcept added | ✅ `FUNC_NOEXCEPT_ADDED` | ✅ | ✅ | C++17: part of function type |
| noexcept removed | ✅ `FUNC_NOEXCEPT_REMOVED` | ✅ | ✅ | |
| Method became virtual | ✅ `FUNC_VIRTUAL_ADDED` | ✅ | ✅ | Mangled name changes |
| Method became non-virtual | ✅ `FUNC_VIRTUAL_REMOVED` | ✅ | ✅ | |
| Global var removed | ✅ `VAR_REMOVED` | ✅ | ✅ | |
| Global var added | ✅ `VAR_ADDED` | ✅ | ✅ | |
| Global var type changed | ✅ `VAR_TYPE_CHANGED` | ✅ | ✅ | |
| Struct/class size changed | ✅ `TYPE_SIZE_CHANGED` | ✅ | ✅ | |
| Alignment changed | ✅ `TYPE_ALIGNMENT_CHANGED` | ✅ | ✅ | |
| Field removed | ✅ `TYPE_FIELD_REMOVED` | ✅ | ✅ | |
| Field added (breaking) | ✅ `TYPE_FIELD_ADDED` | ✅ | ✅ | |
| Field offset changed | ✅ `TYPE_FIELD_OFFSET_CHANGED` | ✅ | ✅ | |
| Field type changed | ✅ `TYPE_FIELD_TYPE_CHANGED` | ✅ | ✅ | |
| Base class changed | ✅ `TYPE_BASE_CHANGED` | ✅ | ✅ | |
| Vtable changed | ✅ `TYPE_VTABLE_CHANGED` | ✅ | ✅ | |
| Type removed | ✅ `TYPE_REMOVED` | ✅ | ✅ | |
| Type added | ✅ `TYPE_ADDED` | ✅ | ✅ | |
| SONAME missing | ✅ case05 | ✅ | ✅ | ELF policy |
| Symbol visibility leak | ✅ case06 | ✅ | ✅ | ELF policy |
| Symbol versioning missing | ✅ case13 | ✅ | ✅ | ELF policy |
| Dependency ABI leak | ✅ case18 | ⚠️ partial | ⚠️ partial | Via transitive header analysis |

---

## GAPS — what abicheck DOES NOT cover (but ABICC/abidiff do)

### P0 — Critical (binary ABI breaks silently missed)

| Case | ABICC | abidiff | Notes | Impact |
|------|-------|---------|-------|--------|
| **Method became static / non-static** | ✅ `Method_Became_Static` | ✅ | Changes mangled name (static lacks implicit `this`) → old binaries get `undefined symbol`. `FUNC_STATIC_CHANGED` covers both directions. | Crash at runtime |
| **Method became const / non-const** | ✅ `Method_Became_Const` | ✅ | Itanium ABI encodes cv-qualifier on `this` (`_ZNK...` for const) | `undefined symbol` |
| **Method became volatile / non-volatile** | ✅ `Method_Became_Volatile` | ✅ | Part of mangled name; rare in practice but still a hard ABI break | `undefined symbol` |
| **Enum member value changed** | ✅ `Enum_Member_Value` | ✅ | Old binaries pass stale integer value → switch corruption in library. (Note: technically UB only if library switch has no default; guaranteed behavioral mismatch regardless.) | Silent corruption |
| **Virtual method position changed** | ✅ `Virtual_Method_Position` | ✅ | vtable slot reorder — old binary calls wrong function via stale slot index. No symbol error. Sprint 1 scope: single-inheritance detection only; full multi-inheritance requires hierarchy-aware vtable reconstruction. | Silent corruption |
| **Added pure virtual method** | ✅ `Added_Pure_Virtual_Method` | ✅ | Old derived class vtable has null/placeholder slot for the new pure virtual → null function pointer call at runtime. Distinct from "added virtual". | Crash at runtime |
| **Enum member removed** | ✅ `Enum_Member_Removed` | ✅ | Old binaries pass removed enum value → potential UB in library switch statements; guaranteed behavioral mismatch. | Silent corruption |
| **Union field changes** | ✅ `Added/Removed_Union_Field` | ✅ | abicheck detects union size change but NOT field-level changes. castxml exposes union members; gap is in checker, not data availability. | Missed layout bugs |
| **Virtual method became pure** | ✅ `Virtual_Method_Became_Pure` | ✅ | Adding `= 0` to existing virtual: old derived class vtable has no implementation slot → null pointer call. Same severity as "added pure virtual". *(Promoted from P1.)* | Crash at runtime |
| **Base class position reordered** | ✅ `Base_Class_Position` | ✅ | `this` pointer adjustment offsets change → existing binaries calling methods on wrong base silently corrupt memory. Multiple inheritance scenario. *(Promoted from P1.)* | Silent corruption |

### P1 — Important (real-world ABI issues, not always immediate crashes)

| Case | ABICC | abidiff | Notes |
|------|-------|---------|-------|
| **Function became deleted** (`= delete`) | ✅ | ❌ | Hard break: previously callable function now deleted. Old binaries fail at link or runtime. |
| **Enum member renamed** (same value) | ✅ `Enum_Member_Name` | ❌ | Source break, semantic confusion |
| **Enum last member value changed** | ✅ `Enum_Last_Member_Value` | ✅ | Boundary/sentinel value changes break switch ranges |
| **Parameter default value changed/removed** | ✅ `Parameter_Default_Value_Changed` | ❌ | Source-level break; old callers pass stale defaults |
| **Global data value changed** (initial value) | ✅ `Global_Data_Value_Changed` | ✅ | Old binaries use compile-time-inlined old value |
| **Global data became const / non-const** | ✅ `Global_Data_Became_Const` | ✅ | Write to now-const data → SIGSEGV |
| **Typedef base type changed** | ✅ `Typedef_BaseType` | ✅ | `typedef int T` → `typedef long T` — size/semantic change. **Note: treat as P0 for Intel library CI** (dnnl_dim_t, primitive impl typedefs). |
| **Type became opaque** | ✅ `Type_Became_Opaque` | ✅ | Was complete struct, now forward-decl only; breaks stack allocation |
| **Anonymous struct/union changes** | ⚠️ | ✅ (test44,45) | castxml assigns IDs to anon types but field path tracking needs validation — **TODO: verify with castxml dump before Sprint 2 commitment.** |
| **Base class became virtual/non-virtual** | ✅ `Base_Class_Became_Virtually_Inherited` | ✅ | Diamond inheritance layout change |
| **Destructor ABI changes** | ✅ | ✅ | Itanium ABI has D0/D1/D2 destructors with separate vtable slots. Adding/removing virtual destructor, or trivial→non-trivial change, has specific ABI impact. |

### P2 — Nice to have (completeness / tooling quality)

| Case | ABICC | abidiff | Notes |
|------|-------|---------|-------|
| **Renamed field** | ✅ `Renamed_Field` | ❌ | Semantic indicator, not hard break |
| **Renamed parameter** | ✅ `Renamed_Parameter` | ❌ | Affects named-arg APIs |
| **Field became mutable** | ✅ `Field_Became_Mutable` | ❌ | Semantic concern |
| **Field became volatile** | ✅ `Field_Became_Volatile` | ❌ | |
| **Field became const** | ✅ `Field_Became_Const` | ❌ | |
| **Return type pointer level change** | ✅ | ✅ | `T*` → `T**` |
| **Parameter pointer level change** | ✅ | ✅ | Missed dereference depth |
| **Symbol alias handling** | ⚠️ | ✅ (test18) | Alias vs real symbol distinction |
| **Calling convention changes** | ✅ (register/stack) | ✅ | ❌ **Fundamentally undetectable from headers** — requires DWARF/binary analysis. Intel libs use SystemV AMD64 consistently; low practical risk. |
| **Cross-architecture ABI diff** | ❌ | ✅ (test23) | 32-bit vs 64-bit comparison |
| **Bitfield layout changes** | ✅ | ✅ | castxml exposes `bit_field` attribute — detectable |
| **Constant added/removed/changed** | ✅ | ❌ | `#define` / `constexpr` constant changes |
| **Template instantiation ABI** | ⚠️ | ⚠️ | Full template diff: out of scope for headers-only approach. **Partial coverage possible**: explicit template instantiations (`template class Foo<int>`) are visible in ELF symtab → trackable via readelf. |
| **Move constructor/assignment ABI** | ❌ | ✅ | Trivially copyable → non-trivial changes calling convention in Itanium (pass-by-register vs pass-by-stack) |
| **CRC/ABI fingerprint** | ❌ | ✅ | Hash-based ABI identity for kernel modules |
| **BTF/CTF format support** | ❌ | ✅ | Kernel/BPF use cases — out of scope |

---

## Open Issues in Upstream Projects

### ABICC (lvc/abi-compliance-checker)

> ABICC's feature set is effectively **frozen** (last release 2023, very low issue velocity on GitHub). The 90+ rules in `RulesBin.xml` represent a stable, complete catalog — all major C++ ABI break patterns are already enumerated there. Open issues (#132-#136) are toolchain/maintenance items, not feature requests.
>
> **Opportunity for abicheck:** implement ABICC's full rule catalog with a modern, CI-friendly architecture. Key differentiators we can offer that ABICC doesn't: no GCC dependency, header-only analysis, structured JSON output, suppression files, Python API.

### libabigail (sourceware.org)

libabigail is actively maintained. Key themes from recent work:

- **PR24552**: Qualified type handling (const/volatile array folding) — affects field type change detection
- **PR27985**: Anonymous struct/union diff accuracy — relevant to our P1 gap
- **PR27616**: Compressed diff output for large libraries — output format inspiration
- **PR25058**: Real-world lttng-ctl regression test
- **PR18166/18791**: libtirpc/complex type diffs

libabigail's focus is DWARF accuracy and kernel/BTF support. Our headers-based approach is complementary, not competing.

---

## Architecture: abicheck vs abidiff

```text
abicheck workflow:         abidiff workflow:
  headers + .so             debug .so (with DWARF)
       ↓                         ↓
  castxml (Clang AST)       DWARF parser
       ↓                         ↓
  type graph                type graph
       ↓                         ↓
  readelf (symtab)          DWARF symtab
       ↓                         ↓
  diff engine               diff engine
```

**Unique advantage:** Release builds (no `-g`) + headers → works in CI/CD without debug artifacts.

**Limitations:**
- Cannot detect calling-convention register/stack changes (not in AST)
- **Header/binary mismatch risk:** if the headers used for analysis don't exactly match what was compiled (e.g., internal headers were used during build), castxml produces a different view than what's in the binary. This is a fundamental correctness risk — abicheck results are only as accurate as the provided headers.
- Cannot detect inline function body changes (inlined calls disappear from symtab)
- Exception handling table changes (`.eh_frame`/LSDA) are binary-level only

---

## Recommended Implementation Order

### Sprint 1 — P0 core + Quick wins (close critical gaps)

**P0 items (8 of 10 — excluding vtable reorder and base class position which need design):**

1. **Enum member removed** → `ENUM_MEMBER_REMOVED` (BREAKING)
   - castxml: full enum member list → compare old vs new

2. **Method static changed** → `FUNC_STATIC_CHANGED` (BREAKING; covers both directions)
   - castxml `static` attribute; cross-check via readelf symbol presence

3. **Method const/volatile changed** → `FUNC_CV_CHANGED` (BREAKING)
   - castxml `const`/`volatile` attributes on methods

4. **Added pure virtual method** → `FUNC_PURE_VIRTUAL_ADDED` (BREAKING)
   - castxml `pure_virtual` attribute; distinct from `FUNC_VIRTUAL_ADDED`

5. **Union field-level changes** → `UNION_FIELD_ADDED` / `UNION_FIELD_REMOVED` / `UNION_FIELD_TYPE_CHANGED`
   - Extend field diff to handle `kind="union"` separately

6. **Enum member value changed** → `ENUM_MEMBER_VALUE_CHANGED` (BREAKING)
   - Compare enum member integer values (not just type-level)

7. **Virtual method became pure** → `FUNC_VIRTUAL_BECAME_PURE` (BREAKING) *(was P1)*
   - castxml `pure_virtual` on existing virtual

**Sprint 1 Quick Wins (low-effort P1 items, free riders with above):**

8. **Enum last/boundary member value** → `ENUM_LAST_MEMBER_CHANGED` — free rider with #6
9. **Typedef base type changed** → `TYPEDEF_BASE_CHANGED` — single castxml attribute lookup; **treat as P0 for Intel CI**
10. **Bitfield layout** → `FIELD_BITFIELD_CHANGED` — castxml `bit_field` + `bits` attribute

**Sprint 1 Design Spike (1 week before implementation):**

- **Virtual method position / vtable reorder** (`VTABLE_SLOT_REORDER`): Sprint 1 scope = single-inheritance only (declaration order = vtable order for Itanium in simple cases). Full multi-inheritance requires class lattice traversal → Sprint 2 follow-up.
- **Base class position reordered** (`BASE_CLASS_POSITION_CHANGED`): castxml exposes base class list order. Spike to validate detection heuristic.

### Sprint 2 — Remaining P0 + P1

11. **Base class position reordered** (after spike validation)
12. **Virtual method position** (full multi-inheritance version)
13. **Global data const qualifier** (`VAR_BECAME_CONST` / `VAR_LOST_CONST`)
14. **Type became opaque** (complete struct → forward-decl detection)
15. **Base class became virtual/non-virtual** (`BASE_CLASS_VIRTUAL_CHANGED`)
16. **Function became deleted** (`FUNC_DELETED`)
17. **Destructor ABI changes** (D0/D1/D2 vtable slot tracking)
18. **Anonymous struct/union** (after castxml behavior validation)

### Sprint 3 — P2 + Completeness

19. **Parameter default value changes** (castxml exposes `default` expressions)
20. **Field qualifiers** (volatile, mutable, const tracking on fields)
21. **Renamed field/parameter** (rename heuristic: same offset + compatible type)
22. **Pointer level changes** (`PARAM_POINTER_LEVEL_CHANGED`, `RETURN_POINTER_LEVEL_CHANGED`)
23. **Explicit template instantiation tracking** (via readelf symtab, not full template analysis)
24. **Parameter defaults** (castxml `default` expression nodes)
25. **ABIXML export** *(scope TBD — libabigail XML schema is complex; needs dedicated planning)*

**Exit criterion for each sprint:** run abicheck on dnnl APT 2025.10→2025.11 and verify no P0 false negatives introduced.

---

## Coverage Summary Table

| Category | abicheck (current, S1-6) | ABICC | abidiff |
|----------|-------------------------|-------|---------|
| Function symbol ABI | 12/12 | 12/12 | 10/12 |
| Type/struct layout | 10/10 | 10/10 | 10/10 |
| C++ vtable | 5/5 | 5/5 | 5/5 |
| Enums | 4/4 | 4/4 | 3/4 |
| Qualifiers (const/volatile) | 5/6 | 6/6 | 4/6 |
| ELF/policy | 4/4 | 3/4 | 4/4 |
| Union | 4/4 | 4/4 | 4/4 |
| Calling convention (DWARF) | 3/4 | 4/4 | 4/4 |
| **Total** | **~43/49 (88%)** | **~48/49** | **~44/49** |

> Calling convention detection is now partially covered via DWARF `DW_AT_calling_convention` (Sprint 4).
> Remaining gaps are P2 items (field qualifiers, renamed parameters, cross-arch support).
