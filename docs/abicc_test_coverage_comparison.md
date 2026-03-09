# ABICC vs Abicheck: Test Coverage Comparison

> Generated: 2026-03-09
> Source: ABICC `RulesBin.xml` (155 rules), `RulesSrc.xml` (101 rules), `RegTests.pm` (~65 scenarios)
> Target: abicheck examples/ (28 cases), tests/ (540+ tests), ChangeKind enum (68 kinds)

---

## Coverage Summary

| Metric | Value |
|--------|-------|
| ABICC de-duplicated scenarios | ~49 |
| Abicheck covers (has ChangeKind + tests) | ~43/49 (88%) |
| Missing detectors (no ChangeKind) | ~21 (mostly P2 source-level) |
| Abicheck example cases | 28 |
| Example cases missing for existing detectors | 12 |
| ABICC RegTest-only scenarios (not in abicheck) | ~10 |

---

## Detailed Rule Mapping

### 1. Virtual Method Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Added_Virtual_Method` (+ leaf variants) | `FUNC_VIRTUAL_ADDED` | case09 | test_checker, test_changekind_coverage | COVERED |
| `Added_Pure_Virtual_Method` | `FUNC_PURE_VIRTUAL_ADDED` | case23 | test_changekind_coverage | COVERED |
| `Removed_Virtual_Method` / `Removed_Pure_Virtual_Method` | `FUNC_VIRTUAL_REMOVED` | case09 | test_checker | COVERED |
| `Virtual_Method_Position` / `Pure_Virtual_Method_Position` | `TYPE_VTABLE_CHANGED` | case09 | test_checker | COVERED |
| `Virtual_Replacement` / `Pure_Virtual_Replacement` | `TYPE_VTABLE_CHANGED` | case09 | test_checker | COVERED |
| `Virtual_Method_Became_Pure` | `FUNC_VIRTUAL_BECAME_PURE` | case23 | test_changekind_coverage | COVERED |
| `Virtual_Method_Became_Non_Pure` | (implicit via vtable diff) | - | partial | PARTIAL |
| `Overridden_Virtual_Method` (A/B) | `TYPE_VTABLE_CHANGED` | case09 | test_checker | COVERED |

### 2. Class/Type Size Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Size_Of_Allocable_Class_Increased/Decreased` | `TYPE_SIZE_CHANGED` | case14 | test_checker | COVERED |
| `Size_Of_Copying_Class` | `TYPE_SIZE_CHANGED` | case14 | test_checker | COVERED |
| `DataType_Size` / `DataType_Size_And_Stack` | `TYPE_SIZE_CHANGED` | case07 | test_checker | COVERED |
| `DataType_Type` | `TYPE_FIELD_TYPE_CHANGED` | - | test_checker | COVERED |

### 3. Base Class Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Base_Class_Position` | `BASE_CLASS_POSITION_CHANGED` | **NONE** | test_sprint2_gap_detectors | COVERED (no example) |
| `Base_Class_Became_Virtually_Inherited` / `Non_Virtually` | `BASE_CLASS_VIRTUAL_CHANGED` | **NONE** | test_sprint2_gap_detectors | COVERED (no example) |
| `Added_Base_Class` (+ Shift/Size/VTable variants, 6 rules) | `TYPE_BASE_CHANGED` | - | test_checker | COVERED |
| `Removed_Base_Class` (+ Shift/Size/VTable variants, 6 rules) | `TYPE_BASE_CHANGED` | - | test_checker | COVERED |

### 4. Field Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Moved_Field` (+ And_Size) | `TYPE_FIELD_OFFSET_CHANGED` | case07 | test_checker | COVERED |
| `Added_Field` (+ Size/Layout variants, 6 rules) | `TYPE_FIELD_ADDED` / `TYPE_FIELD_ADDED_COMPATIBLE` | case07, case14 | test_checker, test_sprint10 | COVERED |
| `Removed_Field` (+ Layout/Size variants, 6 rules) | `TYPE_FIELD_REMOVED` | case07 | test_checker | COVERED |
| `Added_Union_Field` (+ And_Size) | `UNION_FIELD_ADDED` | case26 | test_changekind_coverage | COVERED |
| `Removed_Union_Field` (+ And_Size) | `UNION_FIELD_REMOVED` | case24 | test_changekind_coverage | COVERED |
| `Field_Type` (+ Size/Layout variants, 8 rules) | `TYPE_FIELD_TYPE_CHANGED` | case07 | test_checker | COVERED |
| `Field_BaseType` (+ Size/Format) | `TYPE_FIELD_TYPE_CHANGED` | - | test_checker | COVERED |
| `Struct_Field_Size_Increased` | `STRUCT_FIELD_TYPE_CHANGED` | - | test_sprint3_dwarf | COVERED |
| `Renamed_Field` | - | - | - | **MISSING** (P2) |
| `Used_Reserved_Field` | - | - | - | **MISSING** (P2) |
| `Field_PointerLevel_Increased/Decreased` | - | - | - | **MISSING** (P2, partially via TYPE_FIELD_TYPE_CHANGED) |
| `Field_Became_Volatile/Non_Volatile` | - | - | - | **MISSING** (P2) |
| `Field_Became_Mutable/Non_Mutable` | - | - | - | **MISSING** (P2) |
| `Field_Became_Const/Non_Const` (+ Added/Removed_Const) | - | - | - | **MISSING** (P2) |
| `Field_Became_Private/Protected` | - | - | - | **MISSING** (P2, source-level) |

### 5. Enum Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Enum_Member_Value` | `ENUM_MEMBER_VALUE_CHANGED` | case20 | test_changekind_coverage, test_abicc_parity | COVERED |
| `Enum_Last_Member_Value` | `ENUM_LAST_MEMBER_VALUE_CHANGED` | **NONE** | test_changekind_coverage | COVERED (no example) |
| `Enum_Member_Removed` | `ENUM_MEMBER_REMOVED` | case19 | test_changekind_coverage | COVERED |
| `Added_Enum_Member` | `ENUM_MEMBER_ADDED` | case25 | test_changekind_coverage | COVERED |
| `Enum_Member_Name` (renamed, same value) | - | - | - | **MISSING** (P2, source-level) |

### 6. Typedef Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Typedef_BaseType` (+ Format) | `TYPEDEF_BASE_CHANGED` | **NONE** | test_changekind_coverage | COVERED (no example) |

### 7. Symbol / Function Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Added_Symbol` | `FUNC_ADDED` | case03 | test_checker | COVERED |
| `Removed_Symbol` | `FUNC_REMOVED` | case01, case12 | test_checker | COVERED |
| `Method_Became_Static` / `Non_Static` | `FUNC_STATIC_CHANGED` | case21 | test_changekind_coverage | COVERED |
| `Method_Became_Const` / `Non_Const` | `FUNC_CV_CHANGED` | case22 | test_changekind_coverage | COVERED |
| `Method_Became_Volatile` / `Non_Volatile` | `FUNC_CV_CHANGED` | - | test_changekind_coverage | COVERED |
| `Symbol_Became_Virtual` / `Non_Virtual` | `FUNC_VIRTUAL_ADDED` / `FUNC_VIRTUAL_REMOVED` | case09 | test_checker | COVERED |
| `Method_Became_Private/Protected/Public` | - | - | - | **MISSING** (P2, source-level) |

### 8. Parameter Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Parameter_Type` (+ Register/Stack/Size/Format/BaseType, ~10 rules) | `FUNC_PARAMS_CHANGED` | case02 | test_checker, test_abicc_parity | COVERED |
| `Added/Removed_Parameter` (+ Middle/Unnamed, 8 rules) | `FUNC_PARAMS_CHANGED` | case02 | test_checker | COVERED |
| `Parameter_PointerLevel` | - | - | - | **MISSING** (P2, partially via FUNC_PARAMS_CHANGED) |
| `Renamed_Parameter` | - | - | - | **MISSING** (P2, source-level) |
| `Parameter_Default_Value_Changed/Removed/Added` | - | - | - | **MISSING** (P1, source break) |
| `Parameter_Became_Non_Const` / `Removed_Const` | - | - | - | **MISSING** (P2, source-level) |
| `Parameter_Became_Restrict` / `Non_Restrict` | - | - | - | **MISSING** (P2) |
| `Parameter_Became_VaList` / `Non_VaList` | - | - | - | **MISSING** (P2) |

### 9. Return Type Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Return_Type` (+ Size/Register/Stack/Format/BaseType, ~10 rules) | `FUNC_RETURN_CHANGED` | case10 | test_checker, test_abicc_parity | COVERED |
| `Return_Type_Became_Void` / `From_Void` | `FUNC_RETURN_CHANGED` | - | test_checker | COVERED |
| `Return_PointerLevel` | - | - | - | **MISSING** (P2) |
| `Return_Type_Became_Const` / `Added_Const` | - | - | - | **MISSING** (P2) |
| `Return_Value_Became_Volatile` | - | - | - | **MISSING** (P2) |

### 10. Global Data Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Global_Data_Type` (+ Size/Format) | `VAR_TYPE_CHANGED` | case11 | test_checker | COVERED |
| `Global_Data_Size` | `SYMBOL_SIZE_CHANGED` | - | test_sprint2_elf | COVERED |
| `Global_Data_Became_Const` / `Added_Const` | `VAR_BECAME_CONST` | **NONE** | test_sprint2_gap_detectors | COVERED (no example) |
| `Global_Data_Became_Non_Const` / `Removed_Const` | `VAR_LOST_CONST` | **NONE** | test_sprint2_gap_detectors | COVERED (no example) |
| `Global_Data_Value_Changed` | - | - | - | **MISSING** (P1) |
| `Global_Data_Became_Private/Protected/Public` | - | - | - | **MISSING** (P2, source-level) |

### 11. Constants

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Changed_Constant` | - | - | - | **MISSING** (P2) |
| `Added_Constant` | - | - | - | **MISSING** (P2) |
| `Removed_Constant` | - | - | - | **MISSING** (P2) |

### 12. Opaque Types

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Type_Became_Opaque` | `TYPE_BECAME_OPAQUE` | **NONE** | test_sprint2_gap_detectors | COVERED (no example) |

### 13. Bitfield / Calling Convention

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| Bitfield layout changes | `FIELD_BITFIELD_CHANGED` | **NONE** | test_changekind_coverage | COVERED (no example) |
| Calling convention (register/stack) | `CALLING_CONVENTION_CHANGED` | **NONE** | test_sprint4_dwarf_advanced | COVERED (no example) |

---

## Abicheck-only detectors (not in ABICC)

These detectors exist in abicheck but have no ABICC equivalent:

| ChangeKind | Description | Example |
|------------|-------------|---------|
| `SONAME_CHANGED` | SONAME metadata changed | case05 |
| `NEEDED_ADDED` / `NEEDED_REMOVED` | DT_NEEDED dependencies | - |
| `RPATH_CHANGED` / `RUNPATH_CHANGED` | Search path changes | - |
| `SYMBOL_BINDING_CHANGED` / `STRENGTHENED` | GLOBAL↔WEAK | case27 |
| `SYMBOL_TYPE_CHANGED` | FUNC→OBJECT, etc. | - |
| `SYMBOL_SIZE_CHANGED` | st_size in .dynsym | - |
| `IFUNC_INTRODUCED` / `IFUNC_REMOVED` | GNU IFUNC transition | case29 |
| `COMMON_SYMBOL_RISK` | STT_COMMON exported | - |
| `SYMBOL_VERSION_*` | Symbol versioning changes | case13 |
| `DWARF_INFO_MISSING` | Debug info stripped | - |
| `STRUCT_PACKING_CHANGED` | packed attribute change | - |
| `TYPE_VISIBILITY_CHANGED` | typeinfo/vtable visibility | - |
| `TOOLCHAIN_FLAG_DRIFT` | Compiler flag changes | - |
| `FUNC_VISIBILITY_CHANGED` | default→hidden visibility | - |
| `FUNC_DELETED` | `= delete` added | - |

---

## ABICC RegTests.pm scenarios not in abicheck

| RegTest Scenario | Description | Priority |
|------------------|-------------|----------|
| `StructToUnion` | struct converted to union | P2 |
| `AnonTypedef` | Anonymous typedef size change | P1 |
| `Callback` | vtable insertion in callback hierarchy | P2 |
| `MethodPtr` / `FieldPtr` | Pointer-to-member type changes | P2 |
| `TestRefChange` | Reference parameter field changes | P2 |
| `arraySize` | Array size in parameter changes | P2 |
| `parameterBecameConstInt` | const added to int parameter | P2 |
| `Removed_Const_Overload` | Const overload of method removed | P2 |
| `renamedFunc` | Function renamed (source-compat macro) | P2 |

---

## Missing example cases (detector exists but no example/ directory)

These ChangeKinds have unit test coverage but lack a standalone `examples/caseNN_*` directory:

1. `BASE_CLASS_POSITION_CHANGED` — base class reorder
2. `BASE_CLASS_VIRTUAL_CHANGED` — base became virtual/non-virtual
3. `FUNC_DELETED` — `= delete` added
4. `VAR_BECAME_CONST` — global var became const
5. `VAR_LOST_CONST` — global var lost const
6. `TYPE_BECAME_OPAQUE` — struct became forward-decl only
7. `TYPEDEF_BASE_CHANGED` — typedef underlying type changed
8. `CALLING_CONVENTION_CHANGED` — calling convention drift
9. `STRUCT_PACKING_CHANGED` — packed attribute change
10. `TYPE_VISIBILITY_CHANGED` — typeinfo/vtable visibility
11. `FUNC_VISIBILITY_CHANGED` — function visibility changed
12. `FIELD_BITFIELD_CHANGED` — bitfield layout change
13. `ENUM_LAST_MEMBER_VALUE_CHANGED` — sentinel enum value changed

---

## Recommendations

### High priority (P1 gaps)
1. Add `Parameter_Default_Value_Changed` detector — source break, affects old callers
2. Add `Global_Data_Value_Changed` detector — old binaries use stale inlined values
3. Add `AnonTypedef` / anonymous struct detection — tested by ABICC but missing here

### Medium priority (example case gaps)
4. Create example cases for the 13 detectors listed above that lack examples
5. These are valuable for documentation, demos, and integration testing

### Low priority (P2 completeness)
6. Field qualifier tracking (const, volatile, mutable)
7. Pointer level change tracking (separate from type change)
8. Parameter/return const/restrict/volatile qualifiers
9. Renamed field/parameter detection
10. Constant (#define/constexpr) tracking
11. Access control changes (private/protected/public)
