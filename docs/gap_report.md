# ABI Checker Gap Analysis — abicheck vs ABICC vs libabigail

> Generated: 2026-03-07  
> abicheck version: HEAD of `napetrov/abicheck`  
> Compared against: ABICC (lvc/abi-compliance-checker) + libabigail (abidiff/abidw)

---

## Summary

- **abicheck covers:** ~18/60+ ABICC binary rule scenarios, ~12/40+ libabigail diff scenarios
- **Key differentiator:** abicheck uses castxml (parses headers) → works on **release builds** with headers + `.so`, no debug symbols required. ABICC needs GCC `-fdump-lang-spec`, abidiff needs DWARF.
- **Critical gaps:** 7 P0 cases where we silently miss real ABI breaks

---

## What abicheck ALREADY covers

| Case | abicheck | ABICC | abidiff | Notes |
|------|----------|-------|---------|-------|
| Function removed | ✅ `FUNC_REMOVED` | ✅ | ✅ | Via readelf symtab |
| Function added | ✅ `FUNC_ADDED` | ✅ | ✅ | |
| Return type changed | ✅ `FUNC_RETURN_CHANGED` | ✅ | ✅ | |
| Parameter type changed | ✅ `FUNC_PARAMS_CHANGED` | ✅ | ✅ | |
| noexcept added | ✅ `FUNC_NOEXCEPT_ADDED` | ✅ | ✅ | C++17: part of type |
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
| Dependency ABI leak | ✅ case18 | ⚠️ | ⚠️ | Via transitive header analysis |

---

## GAPS — what abicheck DOES NOT cover (but ABICC/abidiff do)

### P0 — Critical (binary ABI breaks silently missed)

| Case | ABICC | abidiff | Notes | Impact |
|------|-------|---------|-------|--------|
| **Method became static / non-static** | ✅ `Method_Became_Static` | ✅ | Changes mangled name → old binaries get `undefined symbol` | Crash at runtime |
| **Method became const / non-const** | ✅ `Method_Became_Const` | ✅ | C++ mangling includes const qualifier | `undefined symbol` |
| **Method became volatile / non-volatile** | ✅ `Method_Became_Volatile` | ✅ | Part of mangled name | `undefined symbol` |
| **Virtual method position changed** | ✅ `Virtual_Method_Position` | ✅ | vtable slot reorder — calls wrong method, no symbol error | Silent corruption |
| **Added pure virtual method** | ✅ `Added_Pure_Virtual_Method` | ✅ | Distinct from added virtual: forces subclass re-implementation | App won't link/crashes |
| **Enum member removed** | ✅ `Enum_Member_Removed` | ✅ | Old binaries pass removed enum value to library → UB | Silent corruption |
| **Union field changes** | ✅ `Added/Removed_Union_Field` | ✅ | abicheck detects union size change but NOT field-level union changes | Missed layout bugs |

### P1 — Important (frequently requested, real-world ABI issues)

| Case | ABICC | abidiff | Notes |
|------|-------|---------|-------|
| **Enum member renamed** (same value) | ✅ `Enum_Member_Name` | ❌ | Source break, semantic confusion |
| **Enum last member value changed** | ✅ `Enum_Last_Member_Value` | ✅ | Boundary/sentinel value changes break switches |
| **Enum member value changed** | ✅ `Enum_Member_Value` | ✅ | abicheck detects type changes but not enum value semantics |
| **Parameter default value changed/removed** | ✅ `Parameter_Default_Value_Changed` | ❌ | Source-level break; old callers pass stale defaults |
| **Global data value changed** (initial value) | ✅ `Global_Data_Value_Changed` | ✅ | Old binaries use compile-time-inlined old value |
| **Global data became const / non-const** | ✅ `Global_Data_Became_Const` | ✅ | Write to now-const data → SIGSEGV |
| **Typedef base type changed** | ✅ `Typedef_BaseType` | ✅ | `typedef int T` → `typedef long T` — size/semantic change |
| **Type became opaque** | ✅ `Type_Became_Opaque` | ✅ | Was complete struct, now forward-decl only; breaks stack allocation |
| **Anonymous struct/union changes** | ⚠️ | ✅ (test44,45) | abicheck may miss anon type tracking via castxml |
| **Base class became virtual/non-virtual** | ✅ `Base_Class_Became_Virtually_Inherited` | ✅ | Diamond inheritance layout change |
| **Base class position reordered** | ✅ `Base_Class_Position` | ✅ | Memory layout shifts |
| **Virtual method became pure** | ✅ `Virtual_Method_Became_Pure` | ✅ | Forces override; old derived classes crash |

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
| **Calling convention changes** | ✅ (register/stack) | ✅ | abicheck can't detect without DWARF/binary analysis |
| **Cross-architecture ABI diff** | ❌ | ✅ (test23) | 32-bit vs 64-bit comparison |
| **Bitfield layout changes** | ✅ | ✅ | Compiler/flag-dependent — abicheck may partially catch via size |
| **Constant added/removed/changed** | ✅ | ❌ | `#define` / `constexpr` constant changes |
| **CRC/ABI fingerprint** | ❌ | ✅ | Hash-based ABI identity for kernel modules (BTF, CTF) |
| **BTF/CTF format support** | ❌ | ✅ | Kernel/BPF use cases |

---

## Open Issues in upstream (feature requests we could implement)

### ABICC issues (open PRs/issues as of 2026-03)

- **#136**: Fix tests building with recent GCC 15 — not relevant (our toolchain uses castxml/clang)
- **#135**: include `stdlib.h` in test libsample.c — not relevant
- **#132**: Request a new release — project maintenance signal (low activity, last release 2023)

> **Note:** ABICC's GitHub is low-traffic. The main feature gaps are well-established in the rules engine (`RulesBin.xml`) — all 90+ rules are already implemented there. Key missing features that _we_ could implement better:
> - Enum value semantic checks (not just type-level)
> - Default argument tracking
> - Pure virtual distinction

### libabigail issues (sourceware.org Bugzilla)

Key themes from recent libabigail work (PRs in test suite):
- **PR24552**: Qualified type handling (const/volatile array folding) — affects field type change detection
- **PR27985**: Anonymous struct/union diff accuracy  
- **PR27616**: Squished/compressed diff output for large libraries
- **PR25058**: Real-world lttng-ctl regression test
- **PR18166/18791**: libtirpc/complex type diffs

> libabigail is actively maintained. Their focus is DWARF accuracy and kernel/BTF support. Our castxml approach covers the same type-level changes but from headers.

---

## Architecture Advantage of abicheck

```
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
**Limitation:** Can't detect calling-convention register/stack changes without binary analysis.

---

## Recommended Implementation Order

### Sprint 1 — P0 fixes (close critical gaps)

1. **Enum member removed detection**  
   - castxml gives full enum member list → compare old vs new members → flag removed ones  
   - New `ChangeKind`: `ENUM_MEMBER_REMOVED` (BREAKING)

2. **Method became static/non-static detection**  
   - castxml `static` attribute → compare → `FUNC_BECAME_STATIC` (BREAKING, mangling change)  
   - Cross-check via readelf: mangled name presence/absence confirms it

3. **Method became const/non-const/volatile**  
   - castxml `const`/`volatile` attributes on methods → `FUNC_CONST_CHANGED` (BREAKING)  
   - Also affects mangled name

4. **Added pure virtual method (distinct from added virtual)**  
   - castxml `pure_virtual` attribute → `FUNC_PURE_VIRTUAL_ADDED` (BREAKING — forces override)

5. **Virtual method position tracking**  
   - Track vtable slot index per virtual method; detect reordering → `VTABLE_SLOT_REORDER`  
   - castxml gives declaration order; sufficient for vtable slot estimation

6. **Union field-level changes**  
   - Extend field diff to handle `kind="union"` separately  
   - New kinds: `UNION_FIELD_ADDED`, `UNION_FIELD_REMOVED`, `UNION_FIELD_TYPE_CHANGED`

7. **Enum value changes**  
   - Compare enum member integer values (not just type) → `ENUM_MEMBER_VALUE_CHANGED`

### Sprint 2 — P1 (important)

8. **Global data const qualifier tracking** (`VAR_BECAME_CONST` / `VAR_LOST_CONST`)
9. **Typedef base type changes** (castxml fully exposes typedef chains)
10. **Type became opaque** (complete struct → forward-decl detection)
11. **Base class inheritance type** (virtual vs non-virtual inheritance change)
12. **Virtual method became pure** (`FUNC_VIRTUAL_BECAME_PURE`)
13. **Enum last/boundary member value** (sentinel pattern detection)

### Sprint 3 — P2 (completeness)

14. **Parameter default value changes** (castxml exposes `default` expressions)
15. **Field qualifiers** (volatile, mutable, const tracking on fields)
16. **Renamed field/parameter** (rename heuristic: same offset + compatible type)
17. **Pointer level changes** (count `*` depth in type → `PARAM_POINTER_LEVEL_CHANGED`)
18. **Return type pointer level** (same)
19. **Bitfield layout** (castxml `bit_field` attribute)
20. **ABIXML export** (output libabigail-compatible XML for interop with abidiff ecosystem)

---

## Coverage Summary Table

| Category | abicheck | ABICC | abidiff |
|----------|----------|-------|---------|
| Function symbol ABI | 8/12 | 12/12 | 10/12 |
| Type/struct layout | 8/10 | 10/10 | 10/10 |
| C++ vtable | 2/5 | 5/5 | 5/5 |
| Enums | 0/4 | 4/4 | 3/4 |
| Qualifiers (const/volatile) | 0/6 | 6/6 | 4/6 |
| ELF/policy | 4/4 | 3/4 | 4/4 |
| Union | 1/4 | 4/4 | 4/4 |
| Calling convention | 0/4 | 4/4 | 4/4 |
| **Total (est.)** | **~23/49** | **~48/49** | **~44/49** |

**Bottom line:** abicheck covers ~47% of known ABI break scenarios. Sprint 1 (7 cases) would push coverage to ~62%, Sprint 2 to ~75%, Sprint 3 to ~90%.
