# ABICC vs Abicheck: Test Coverage Comparison

> Updated: 2026-03-09
> Source: ABICC `RulesBin.xml` (195 rules), `RulesSrc.xml` (101 rules), `RegTests.pm` (~160 scenarios)
> Target: abicheck `examples/` (41 cases), `tests/` (540+ tests), `ChangeKind` enum (85 kinds)

---

## Coverage Summary

| Metric | Value |
|--------|-------|
| ABICC binary rules (RulesBin.xml) | 195 |
| ABICC source rules (RulesSrc.xml) | 101 |
| ABICC RegTests.pm scenarios | ~160 |
| ABICC de-duplicated scenarios | ~65 |
| Abicheck covers (has ChangeKind + tests) | ~57/65 (88%) |
| Abicheck ChangeKind enum members | 85 |
| Abicheck example cases | 41 |
| Detectors with example case | 52/85 |
| Detectors without example case | 13 (unit-tested only) |
| ABICC scenarios NOT in abicheck | ~8 |
| Abicheck-only detectors (not in ABICC) | 20 |

---

## Detailed Rule Mapping

### 1. Virtual Method Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Added_Virtual_Method` (+ 4 leaf variants) | `FUNC_VIRTUAL_ADDED` | case09, case38 | test_checker, test_changekind_coverage | **COVERED** |
| `Added_Pure_Virtual_Method` | `FUNC_PURE_VIRTUAL_ADDED` | case23 | test_changekind_coverage | **COVERED** |
| `Added_First_Virtual_Method` | `FUNC_VIRTUAL_ADDED` + `TYPE_VTABLE_CHANGED` | case38 | test_checker | **COVERED** |
| `Removed_Virtual_Method` / `Removed_Pure_Virtual_Method` | `FUNC_VIRTUAL_REMOVED` | case09, case38 | test_checker | **COVERED** |
| `Removed_Last_Virtual_Method` | `FUNC_VIRTUAL_REMOVED` + `TYPE_SIZE_CHANGED` | case38 | test_checker | **COVERED** |
| `Virtual_Method_Position` / `Pure_Virtual_Method_Position` | `TYPE_VTABLE_CHANGED` | case09 | test_checker | **COVERED** |
| `Virtual_Replacement` / `Pure_Virtual_Replacement` | `TYPE_VTABLE_CHANGED` | case09 | test_checker | **COVERED** |
| `Virtual_Method_Became_Pure` | `FUNC_VIRTUAL_BECAME_PURE` | case23 | test_changekind_coverage | **COVERED** |
| `Virtual_Method_Became_Non_Pure` | (implicit via vtable diff) | case38 | partial | **PARTIAL** — no dedicated ChangeKind |
| `Virtual_Table_Changed_Unknown` | `TYPE_VTABLE_CHANGED` | case09 | test_checker | **COVERED** |
| `Overridden_Virtual_Method` (A/B) | `TYPE_VTABLE_CHANGED` | case09 | test_checker | **COVERED** |
| `VirtualTableSize` (RegTest) | `TYPE_VTABLE_CHANGED` + `TYPE_SIZE_CHANGED` | case09 | test_checker | **COVERED** |

### 2. Class/Type Size Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Size_Of_Allocable_Class_Increased/Decreased` | `TYPE_SIZE_CHANGED` | case14 | test_checker | **COVERED** |
| `Size_Of_Copying_Class` | `TYPE_SIZE_CHANGED` | case14 | test_checker | **COVERED** |
| `DataType_Size` / `DataType_Size_And_Stack` | `TYPE_SIZE_CHANGED` | case07, case40 | test_checker | **COVERED** |
| `DataType_Type` | `TYPE_FIELD_TYPE_CHANGED` | case41 | test_checker | **COVERED** |

### 3. Base Class Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Base_Class_Position` | `BASE_CLASS_POSITION_CHANGED` | case37 | test_sprint2_gap_detectors | **COVERED** |
| `Base_Class_Became_Virtually_Inherited` / `Non_Virtually` | `BASE_CLASS_VIRTUAL_CHANGED` | case37 | test_sprint2_gap_detectors | **COVERED** |
| `Added_Base_Class` (+ Shift/Size/VTable variants, 6 rules) | `TYPE_BASE_CHANGED` | case37 | test_checker | **COVERED** |
| `Removed_Base_Class` (+ Shift/Size/VTable variants, 6 rules) | `TYPE_BASE_CHANGED` | case37 | test_checker | **COVERED** |

### 4. Field Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Moved_Field` (+ And_Size) | `TYPE_FIELD_OFFSET_CHANGED` | case07, case40 | test_checker | **COVERED** |
| `Added_Field` (+ Size/Layout variants, 6 rules) | `TYPE_FIELD_ADDED` / `TYPE_FIELD_ADDED_COMPATIBLE` | case07, case14, case40 | test_checker, test_sprint10 | **COVERED** |
| `Added_Middle_Field_And_Size` (RegTest) | `TYPE_FIELD_ADDED` + `TYPE_FIELD_OFFSET_CHANGED` | case40 | test_checker | **COVERED** |
| `Added_Tail_Field` (RegTest) | `TYPE_FIELD_ADDED_COMPATIBLE` | case40 | test_checker | **COVERED** |
| `Removed_Field` (+ Layout/Size variants, 6 rules) | `TYPE_FIELD_REMOVED` | case07 | test_checker | **COVERED** |
| `Added_Union_Field` (+ And_Size) | `UNION_FIELD_ADDED` | case26 | test_changekind_coverage | **COVERED** |
| `Removed_Union_Field` (+ And_Size) | `UNION_FIELD_REMOVED` | case24 | test_changekind_coverage | **COVERED** |
| `Field_Type` (+ Size/Layout variants, 8 rules) | `TYPE_FIELD_TYPE_CHANGED` | case07, case41 | test_checker | **COVERED** |
| `Field_BaseType` (+ Size/Format) | `TYPE_FIELD_TYPE_CHANGED` | case41 | test_checker | **COVERED** |
| `Struct_Field_Size_Increased` | `STRUCT_FIELD_TYPE_CHANGED` | - | test_sprint3_dwarf | **COVERED** |
| `Renamed_Field` | `FIELD_RENAMED` | case35 | test_sprint7_full_parity | **COVERED** |
| `Used_Reserved_Field` | - | - | - | **MISSING** (P2) |
| `Field_PointerLevel_Increased/Decreased` | (via `TYPE_FIELD_TYPE_CHANGED`) | case33 | test_checker | **PARTIAL** — detected as type change, not dedicated pointer-level |
| `Field_Became_Volatile/Non_Volatile` | `FIELD_BECAME_VOLATILE` / `FIELD_LOST_VOLATILE` | case30 | test_sprint7_full_parity | **COVERED** |
| `Field_Became_Mutable/Non_Mutable` | `FIELD_BECAME_MUTABLE` / `FIELD_LOST_MUTABLE` | case30 | test_sprint7_full_parity | **COVERED** |
| `Field_Became_Const/Non_Const` (+ Added/Removed_Const) | `FIELD_BECAME_CONST` / `FIELD_LOST_CONST` | case30 | test_sprint7_full_parity | **COVERED** |
| `Field_Became_Private/Protected` | `FIELD_ACCESS_CHANGED` | case34 | test_sprint7_full_parity | **COVERED** |
| `Field_Type_Format` / `Field_BaseType_Format` | `TYPE_FIELD_TYPE_CHANGED` | case41 | test_checker | **COVERED** (format distinction not separate) |
| `AddedBitfield` / `BitfieldSize` / `RemovedBitfield` (RegTest) | `FIELD_BITFIELD_CHANGED` | - | test_changekind_coverage | **COVERED** (no example) |

### 5. Enum Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Enum_Member_Value` | `ENUM_MEMBER_VALUE_CHANGED` | case08, case20 | test_changekind_coverage, test_abicc_parity | **COVERED** |
| `Enum_Last_Member_Value` | `ENUM_LAST_MEMBER_VALUE_CHANGED` | - | test_changekind_coverage | **COVERED** (no example) |
| `Enum_Member_Removed` | `ENUM_MEMBER_REMOVED` | case19 | test_changekind_coverage | **COVERED** |
| `Added_Enum_Member` | `ENUM_MEMBER_ADDED` | case25 | test_changekind_coverage | **COVERED** |
| `Enum_Member_Name` (renamed, same value) | `ENUM_MEMBER_RENAMED` | case31 | test_sprint7_full_parity | **COVERED** |
| `Enum_Private_Member_Value` | (not applicable — no private enums in C) | - | - | N/A |

### 6. Typedef Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Typedef_BaseType` (+ Format) | `TYPEDEF_BASE_CHANGED` | case28 | test_changekind_coverage | **COVERED** |
| `Typedef_Removed` | `TYPEDEF_REMOVED` | - | test_changekind_coverage | **COVERED** (no example) |

### 7. Symbol / Function Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Added_Symbol` | `FUNC_ADDED` | case03 | test_checker | **COVERED** |
| `Removed_Symbol` | `FUNC_REMOVED` | case01, case12 | test_checker | **COVERED** |
| `Method_Became_Static` / `Non_Static` | `FUNC_STATIC_CHANGED` | case21 | test_changekind_coverage | **COVERED** |
| `Method_Became_Const` / `Non_Const` | `FUNC_CV_CHANGED` | case22 | test_changekind_coverage | **COVERED** |
| `Method_Became_Volatile` / `Non_Volatile` | `FUNC_CV_CHANGED` | - | test_changekind_coverage | **COVERED** |
| `Symbol_Became_Virtual` / `Non_Virtual` | `FUNC_VIRTUAL_ADDED` / `FUNC_VIRTUAL_REMOVED` | case09, case38 | test_checker | **COVERED** |
| `Symbol_Became_Static` / `Non_Static` | `FUNC_STATIC_CHANGED` | case21 | test_changekind_coverage | **COVERED** |
| `Method_Became_Private/Protected` | `METHOD_ACCESS_CHANGED` | case34 | test_sprint7_full_parity | **COVERED** |
| `Method_Became_Public` | `METHOD_ACCESS_CHANGED` | case34 | test_sprint7_full_parity | **COVERED** |
| `Symbol_Changed_Return` | `FUNC_RETURN_CHANGED` | case10 | test_checker | **COVERED** |
| `Symbol_Changed_Parameters` | `FUNC_PARAMS_CHANGED` | case02 | test_checker | **COVERED** |
| `Global_Data_Symbol_Changed_Type` | `VAR_TYPE_CHANGED` | case11 | test_checker | **COVERED** |
| `Removed_Const_Overload` (RegTest) | - | - | - | **MISSING** (P2) |
| `renamedFunc` (RegTest) | - | - | - | **MISSING** (P2 — source-level macro rename) |

### 8. Parameter Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Parameter_Type` (+ Register/Stack/Size/Format/BaseType, ~15 rules) | `FUNC_PARAMS_CHANGED` | case02 | test_checker, test_abicc_parity | **COVERED** |
| `Added/Removed_Parameter` (+ Middle/Unnamed, 8 rules) | `FUNC_PARAMS_CHANGED` | case02 | test_checker | **COVERED** |
| `Parameter_PointerLevel_Increased/Decreased` | `PARAM_POINTER_LEVEL_CHANGED` | case33 | test_sprint7_full_parity | **COVERED** |
| `Renamed_Parameter` | `PARAM_RENAMED` | - | test_sprint7_full_parity | **COVERED** (no example) |
| `Parameter_Default_Value_Changed` | `PARAM_DEFAULT_VALUE_CHANGED` | case32 | test_sprint7_full_parity | **COVERED** |
| `Parameter_Default_Value_Removed` | `PARAM_DEFAULT_VALUE_REMOVED` | case32 | test_sprint7_full_parity | **COVERED** |
| `Parameter_Default_Value_Added` | (implicit — compatible addition) | case32 | test_sprint7_full_parity | **COVERED** |
| `Parameter_Became_Non_Const` / `Removed_Const` | (via `FUNC_PARAMS_CHANGED`) | - | test_checker | **PARTIAL** — detected as param type change |
| `Parameter_Became_Restrict` / `Non_Restrict` | - | - | - | **MISSING** (P2) |
| `Parameter_Became_VaList` / `Non_VaList` | - | - | - | **MISSING** (P2) |
| `Parameter_Became_Register` / `Non_Register` | - | - | - | **MISSING** (P2 — register allocation detail) |
| `Parameter_To/From/Changed_Register` | - | - | - | **MISSING** (P2 — ABI calling convention detail) |
| `Parameter_Changed_Offset` | - | - | - | **MISSING** (P2 — stack layout detail) |
| `parameterBecameConstInt` (RegTest) | (via `FUNC_PARAMS_CHANGED`) | - | test_checker | **PARTIAL** |

### 9. Return Type Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Return_Type` (+ Size/Register/Stack/Format/BaseType, ~10 rules) | `FUNC_RETURN_CHANGED` | case10 | test_checker, test_abicc_parity | **COVERED** |
| `Return_Type_Became_Void` / `From_Void` (+ Stack/Register variants, 4 rules) | `FUNC_RETURN_CHANGED` | - | test_checker | **COVERED** |
| `Return_PointerLevel_Increased/Decreased` | `RETURN_POINTER_LEVEL_CHANGED` | case33 | test_sprint7_full_parity | **COVERED** |
| `Return_Type_Became_Const` / `Added_Const` | (via `FUNC_RETURN_CHANGED`) | - | test_checker | **PARTIAL** — detected as return type change |
| `Return_Value_Became_Volatile` | (via `FUNC_RETURN_CHANGED`) | - | test_checker | **PARTIAL** — detected as return type change |
| `Return_Type_And_Register_Became/Was_Hidden_Parameter` | - | - | - | **MISSING** (P2 — ABI calling convention detail) |

### 10. Global Data Changes

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Global_Data_Type` (+ Size/Format) | `VAR_TYPE_CHANGED` | case11 | test_checker | **COVERED** |
| `Global_Data_Size` | `SYMBOL_SIZE_CHANGED` | - | test_sprint2_elf | **COVERED** |
| `Global_Data_Became_Const` / `Added_Const` | `VAR_BECAME_CONST` | case39 | test_sprint2_gap_detectors | **COVERED** |
| `Global_Data_Became_Non_Const` / `Removed_Const` | `VAR_LOST_CONST` | case39 | test_sprint2_gap_detectors | **COVERED** |
| `Global_Data_Value_Changed` | - | - | - | **MISSING** (P1) |
| `Global_Data_Became_Private/Protected/Public` | - | - | - | **MISSING** (P2, source-level) |

### 11. Constants (#define / constexpr)

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Changed_Constant` | - | - | - | **MISSING** (P2) |
| `Added_Constant` | - | - | - | **MISSING** (P2) |
| `Removed_Constant` | - | - | - | **MISSING** (P2) |
| `PUBLIC_CONSTANT` / `PUBLIC_VERSION` (RegTest) | - | - | - | **MISSING** (P2) |

### 12. Opaque Types

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| `Type_Became_Opaque` | `TYPE_BECAME_OPAQUE` | case28 | test_sprint2_gap_detectors | **COVERED** |
| `StructBecameOpaque` / `UnionBecameOpaque` (RegTest) | `TYPE_BECAME_OPAQUE` | case28 | test_sprint2_gap_detectors | **COVERED** |
| `paramBecameNonOpaque` (RegTest) | (implicit via type diff) | - | - | **PARTIAL** |

### 13. Bitfield / Calling Convention

| ABICC Rule | Abicheck ChangeKind | Example | Tests | Status |
|------------|---------------------|---------|-------|--------|
| Bitfield layout changes | `FIELD_BITFIELD_CHANGED` | - | test_changekind_coverage | **COVERED** (no example) |
| Calling convention (register/stack) | `CALLING_CONVENTION_CHANGED` | - | test_sprint4_dwarf_advanced | **COVERED** (no example) |
| `callConv`/`callConv2-5` (RegTest) | `CALLING_CONVENTION_CHANGED` (DWARF only) | - | test_sprint4_dwarf_advanced | **PARTIAL** — requires DWARF |

---

## ABICC RegTests.pm Scenarios — Gap Analysis

These are specific regression test scenarios from ABICC's `RegTests.pm` (~160 scenarios) mapped to abicheck coverage:

### Fully Covered RegTest Scenarios

| RegTest Scenario | Abicheck Coverage |
|------------------|-------------------|
| `addedFunc` / `addedFunc2` / `addedFunc3` | `FUNC_ADDED` (case03) |
| `removedFunc2` / `RemovedInterface` | `FUNC_REMOVED` (case01, case12) |
| `AddedInterface` / `AddedVariable` | `FUNC_ADDED` / `VAR_ADDED` (case03) |
| `AddedVirtualMethod` / `AddedVirtualMethodAtEnd` | `FUNC_VIRTUAL_ADDED` (case09, case38) |
| `AddedPureVirtualMethod` | `FUNC_PURE_VIRTUAL_ADDED` (case23) |
| `AddedFirstVirtualMethod` | `FUNC_VIRTUAL_ADDED` + `TYPE_VTABLE_CHANGED` (case38) |
| `RemovedVirtualFunction` / `RemovedPureVirtualMethodFromEnd` | `FUNC_VIRTUAL_REMOVED` (case09, case38) |
| `RemovedLastVirtualMethod` | `FUNC_VIRTUAL_REMOVED` + `TYPE_SIZE_CHANGED` (case38) |
| `VirtualMethodPosition` / `PureVirtualFunctionPosition` | `TYPE_VTABLE_CHANGED` (case09) |
| `VirtualReplacement` / `PureVirtualReplacement` | `TYPE_VTABLE_CHANGED` (case09) |
| `OverriddenVirtualMethod` / `OverriddenVirtualMethodB` | `TYPE_VTABLE_CHANGED` (case09) |
| `BecameVirtualMethod` | `FUNC_VIRTUAL_ADDED` (case38) |
| `MethodBecameStatic` / `MethodBecameNonStatic` | `FUNC_STATIC_CHANGED` (case21) |
| `MethodBecameConst` / `MethodBecameNonConst` | `FUNC_CV_CHANGED` (case22) |
| `MethodBecameVolatile` / `MethodBecameConstVolatile` | `FUNC_CV_CHANGED` (case22) |
| `MethodBecamePrivate` / `MethodBecameProtected` / `MethodBecamePublic` | `METHOD_ACCESS_CHANGED` (case34) |
| `TypeSize` / `AllocableClassSize` / `DecreasedClassSize` / `CopyingClassSize` | `TYPE_SIZE_CHANGED` (case07, case14) |
| `AddedFieldAndSize` / `AddedMiddleFieldAndSize` / `AddedTailField` | `TYPE_FIELD_ADDED` / `TYPE_FIELD_ADDED_COMPATIBLE` (case07, case40) |
| `RemovedFieldAndSize` / `RemovedMiddleFieldAndSize` | `TYPE_FIELD_REMOVED` (case07) |
| `MovedField` | `TYPE_FIELD_OFFSET_CHANGED` (case07, case40) |
| `RenamedField` | `FIELD_RENAMED` (case35) |
| `FieldTypeAndSize` / `MemberType` / `FieldBaseType` | `TYPE_FIELD_TYPE_CHANGED` (case07, case41) |
| `FieldPointerLevel` / `FieldPointerLevelAndSize` | `TYPE_FIELD_TYPE_CHANGED` (case33) |
| `FieldBecameConst` / `FieldRemovedConst` / `FieldBecameConstTypedef` | `FIELD_BECAME_CONST` / `FIELD_LOST_CONST` (case30) |
| `FieldBecameVolatile` / `FieldBecameNonVolatile` | `FIELD_BECAME_VOLATILE` / `FIELD_LOST_VOLATILE` (case30) |
| `FieldBecameMutable` / `FieldBecameNonMutable` | `FIELD_BECAME_MUTABLE` / `FIELD_LOST_MUTABLE` (case30) |
| `FieldBecamePrivate` / `FieldBecameProtected` | `FIELD_ACCESS_CHANGED` (case34) |
| `UnionAddedField` / `UnionRemovedField` | `UNION_FIELD_ADDED` / `UNION_FIELD_REMOVED` (case24, case26) |
| `EnumMemberValue` | `ENUM_MEMBER_VALUE_CHANGED` (case08, case20) |
| `EnumMemberRename` | `ENUM_MEMBER_RENAMED` (case31) |
| `AddedEnumMember` | `ENUM_MEMBER_ADDED` (case25) |
| `ChangedBaseClass` / `ChangedBaseClassAndSize` | `TYPE_BASE_CHANGED` (case37) |
| `BaseClassBecameVirtuallyInherited` / `BecameVirtualBase` | `BASE_CLASS_VIRTUAL_CHANGED` (case37) |
| `funcParameterType` / `funcParameterTypeAndSize` / `funcParameterBaseType` | `FUNC_PARAMS_CHANGED` (case02) |
| `funcParameterPointerLevel` / `funcParameterPointerLevelAndSize` | `PARAM_POINTER_LEVEL_CHANGED` (case33) |
| `funcReturnType` / `funcReturnTypeAndSize` / `funcReturnBaseType` | `FUNC_RETURN_CHANGED` (case10) |
| `funcReturnTypeBecameVoid` | `FUNC_RETURN_CHANGED` (case10) |
| `funcReturnPointerLevel` / `funcReturnPointerLevelAndSize` | `RETURN_POINTER_LEVEL_CHANGED` (case33) |
| `paramDefaultValueChanged_Integer/String/Char/Bool` | `PARAM_DEFAULT_VALUE_CHANGED` (case32) |
| `parameterDefaultValueRemoved` / `parameterDefaultValueAdded` | `PARAM_DEFAULT_VALUE_REMOVED` (case32) |
| `paramDefaultValue_Converted` | `PARAM_DEFAULT_VALUE_CHANGED` (case32) |
| `StructBecameOpaque` / `UnionBecameOpaque` | `TYPE_BECAME_OPAQUE` (case28) |
| `globalDataBecameConst` / `GlobalDataBecameConst` | `VAR_BECAME_CONST` (case39) |
| `globalDataBecameNonConst` / `GlobalDataBecameNonConst` | `VAR_LOST_CONST` (case39) |
| `GlobalDataBecamePrivate` | (via access change detection) | **PARTIAL** |
| `removedParameter` / `addedParameter` | `FUNC_PARAMS_CHANGED` (case02) |
| `TestAlignment` | `TYPE_ALIGNMENT_CHANGED` (case07) |
| `AddedBitfield` / `BitfieldSize` / `RemovedBitfield` / `RemovedMiddleBitfield` | `FIELD_BITFIELD_CHANGED` (unit tests) |
| `OpaqueType` / `InternalType` | `TYPE_BECAME_OPAQUE` / compatible (case28) |
| `parameterTypeFormat_Safe` / `FieldTypeFormat` | `TYPE_FIELD_TYPE_CHANGED` (case41) |
| `parameterTypedefChange` / `FieldTypedefChange` | `FUNC_PARAMS_CHANGED` / `TYPE_FIELD_TYPE_CHANGED` (case41) |
| `ObjectAddedMember` / `AddedMiddlePaddedField` | `TYPE_FIELD_ADDED` (case40) |
| `RemovedVirtualDestructor` | `FUNC_VIRTUAL_REMOVED` + vtable (case38) |
| `UnnamedTypeSize` | `ANON_FIELD_CHANGED` (case36) |
| `funcAnonTypedef` | `ANON_FIELD_CHANGED` (case36) |

### NOT Covered RegTest Scenarios

| RegTest Scenario | Description | Priority | Notes |
|------------------|-------------|----------|-------|
| `StructToUnion` | struct converted to union (aggregate kind change) | P2 | Could be detected via `DataType_Type` but no dedicated detector |
| `TestMethodPtr` / `TestFieldPtr` | Pointer-to-member type changes | P2 | Requires tracking `T::*` types; rare in practice |
| `TestRefChange` / `paramRefChange` | Reference parameter with changed field layout | P2 | Partially detected via `FUNC_PARAMS_CHANGED` |
| `Callback` / `testCallback` | vtable insertion in callback class hierarchy | P2 | Detected indirectly via `TYPE_VTABLE_CHANGED` |
| `arraySize` (C test) | Array dimension change in parameter | P2 | Partially detected as param type change |
| `renamedFunc` | Function renamed with macro alias | P2 | Source-level rename; no ABI break if old symbol kept |
| `Removed_Const_Overload` / `RemovedConstOverload` | Const method overload removed | P2 | Detected as `FUNC_REMOVED` but lacks const-overload-specific rule |
| `ParameterBecameRestrict` / `ParameterBecameNonRestrict` | `restrict` qualifier changes | P2 | No effect on ABI in practice |
| `parameterBecameConstInt` (C test) | `const` added to int parameter | P2 | Partially detected via `FUNC_PARAMS_CHANGED` |
| `GlobalDataValue` / `globalDataValue_Integer/Char` | Global data initial value changed | P1 | **Notable gap** — old binaries use stale inlined values |
| `PUBLIC_CONSTANT` / `PUBLIC_VERSION` / `PRIVATE_CONSTANT` | Preprocessor constant changes | P2 | #define tracking not implemented |
| `UsedReserved` (C test) | Reserved field put into use | P2 | Detected as field type change but no reserved-specific rule |
| `callConv` / `callConv2-5` (C tests) | Calling convention changes (POD types) | P2 | Partially via `CALLING_CONVENTION_CHANGED` (DWARF only) |
| `ChangedTemplate` / `TestRemovedTemplate` / `removedTemplateSpec` | Template specialization changes | P2 | Partial via ELF symbol tracking |
| `RemovedInlineMethod` / `removedInlineFunction` / `InlineMethod` | Inline function/method changes | P2 | Out of scope — inlined symbols not in ELF |
| `functionBecameInline` | Function became inline | P2 | Out of scope — inlined symbols not in ELF |
| `DefaultConstructor` | Default constructor changes | P2 | Detected via symbol presence change |
| `UnsafeVirtualOverride` | Virtual method with incompatible override | P2 | Detected via vtable change |
| `RemovedPrivateVirtualSymbol` / `AddedPrivateVirtualSymbol` | Private virtual method changes | P2 | These affect vtable layout regardless of access |
| `RemovedAddedVirtualSymbol` | Virtual symbol replaced | P2 | Detected via `TYPE_VTABLE_CHANGED` |
| `VirtualFunctionPositionSafe` | Virtual method reorder (safe case) | P2 | Detected but not marked as safe-specific |
| `OutsideNS` | Member field added outside namespace | P2 | Detected via `TYPE_FIELD_ADDED` |
| `paramBecameNonOpaque` | Opaque to transparent type | P2 | Reverse of `TYPE_BECAME_OPAQUE` |

---

## Abicheck-only Detectors (not in ABICC)

These detectors exist in abicheck but have no ABICC equivalent:

| ChangeKind | Description | Example | Category |
|------------|-------------|---------|----------|
| `SONAME_CHANGED` | SONAME metadata changed | case05 | ELF policy |
| `NEEDED_ADDED` / `NEEDED_REMOVED` | DT_NEEDED dependencies | - | ELF policy |
| `RPATH_CHANGED` / `RUNPATH_CHANGED` | Search path changes | - | ELF policy |
| `SYMBOL_BINDING_CHANGED` / `STRENGTHENED` | GLOBAL↔WEAK | case27 | ELF metadata |
| `SYMBOL_TYPE_CHANGED` | FUNC→OBJECT, etc. | - | ELF metadata |
| `SYMBOL_SIZE_CHANGED` | st_size in .dynsym | - | ELF metadata |
| `IFUNC_INTRODUCED` / `IFUNC_REMOVED` | GNU IFUNC transition | case29 | ELF metadata |
| `COMMON_SYMBOL_RISK` | STT_COMMON exported | - | ELF metadata |
| `SYMBOL_VERSION_DEFINED_REMOVED` | Version definition removed | case13 | ELF versioning |
| `SYMBOL_VERSION_REQUIRED_ADDED/REMOVED` | Version requirement changed | case13 | ELF versioning |
| `DWARF_INFO_MISSING` | Debug info stripped | - | DWARF |
| `STRUCT_SIZE_CHANGED` | DWARF-based struct size | - | DWARF layout |
| `STRUCT_FIELD_OFFSET_CHANGED` | DWARF-based field offset | - | DWARF layout |
| `STRUCT_FIELD_REMOVED` / `STRUCT_FIELD_TYPE_CHANGED` | DWARF field changes | - | DWARF layout |
| `STRUCT_ALIGNMENT_CHANGED` | DWARF alignment | - | DWARF layout |
| `ENUM_UNDERLYING_SIZE_CHANGED` | Enum underlying type size | - | DWARF layout |
| `STRUCT_PACKING_CHANGED` | `__attribute__((packed))` change | - | DWARF advanced |
| `TYPE_VISIBILITY_CHANGED` | typeinfo/vtable visibility | - | DWARF advanced |
| `TOOLCHAIN_FLAG_DRIFT` | Compiler flag changes | - | DWARF advanced |
| `FUNC_VISIBILITY_CHANGED` | default→hidden visibility | case06 | Symbol |
| `FUNC_DELETED` | `= delete` added | - | C++ |
| `FUNC_NOEXCEPT_ADDED` / `FUNC_NOEXCEPT_REMOVED` | noexcept changes | case15 | C++17 |
| `ANON_FIELD_CHANGED` | Anonymous struct/union member | case36 | Type |

---

## Detectors with Unit Tests but NO Example Case

These ChangeKinds have test coverage but lack a standalone `examples/caseNN_*` directory:

1. `ENUM_LAST_MEMBER_VALUE_CHANGED` — sentinel enum value changed
2. `TYPEDEF_REMOVED` — typedef removed
3. `CALLING_CONVENTION_CHANGED` — calling convention drift
4. `STRUCT_PACKING_CHANGED` — packed attribute change
5. `TYPE_VISIBILITY_CHANGED` — typeinfo/vtable visibility
6. `FIELD_BITFIELD_CHANGED` — bitfield layout change
7. `FUNC_DELETED` — `= delete` added
8. `PARAM_RENAMED` — parameter name changed
9. `DWARF_INFO_MISSING` — debug info stripped
10. `STRUCT_SIZE/FIELD/ALIGNMENT_CHANGED` — DWARF layout variants
11. `ENUM_UNDERLYING_SIZE_CHANGED` — enum underlying type size
12. `TOOLCHAIN_FLAG_DRIFT` — compiler flag drift
13. `COMMON_SYMBOL_RISK` — STT_COMMON exported

---

## Coverage Statistics

### By detection category

| Category | ABICC Rules | Abicheck Covered | Status |
|----------|-------------|------------------|--------|
| Virtual methods (12 rules) | 15 | 12/12 scenarios | **100%** |
| Class/type size (4 rules) | 5 | 4/4 scenarios | **100%** |
| Base classes (14 rules) | 4 | 4/4 scenarios | **100%** |
| Field changes (42 rules) | 17 | 15/17 scenarios | **88%** |
| Enum changes (6 rules) | 5 | 5/5 scenarios | **100%** |
| Typedef changes (3 rules) | 2 | 2/2 scenarios | **100%** |
| Symbol/function (14 rules) | 12 | 10/12 scenarios | **83%** |
| Parameter changes (20 rules) | 10 | 6/10 scenarios | **60%** |
| Return type (22 rules) | 6 | 4/6 scenarios | **67%** |
| Global data (12 rules) | 6 | 4/6 scenarios | **67%** |
| Constants (4 rules) | 3 | 0/3 scenarios | **0%** |
| Opaque types (1 rule) | 2 | 2/2 scenarios | **100%** |
| Bitfield/calling conv. | 2 | 2/2 scenarios | **100%** |
| **Total** | **~65 scenarios** | **~57/65** | **~88%** |

### Gap summary (ABICC scenarios NOT in abicheck)

| # | Missing Scenario | Priority | Difficulty |
|---|------------------|----------|------------|
| 1 | `Global_Data_Value_Changed` | **P1** | Medium — requires constant propagation analysis |
| 2 | `Changed/Added/Removed_Constant` (preprocessor) | P2 | Hard — #define not in AST; needs preprocessor diff |
| 3 | `Parameter_Became_Restrict/Non_Restrict` | P2 | Easy — castxml attribute |
| 4 | `Parameter_Became_VaList/Non_VaList` | P2 | Easy — type comparison |
| 5 | `Parameter/Return register/stack layout details` | P2 | Hard — ABI calling convention details |
| 6 | `Used_Reserved_Field` | P2 | Medium — heuristic for "__reserved" fields |
| 7 | `StructToUnion` (aggregate kind change) | P2 | Easy — castxml `kind` attribute |
| 8 | `Removed_Const_Overload` (dedicated rule) | P2 | Easy — track const overload pairs |

---

## Recommendations

### High priority (P1 gap)
1. **Add `Global_Data_Value_Changed` detector** — Old binaries use compile-time-inlined old constant values. This is the only remaining P1 gap.

### Medium priority (example case gaps)
2. Create example cases for the 13 detectors that lack `examples/caseNN_*` directories (listed above). These improve documentation and integration testing.

### Low priority (P2 completeness)
3. Add `restrict` qualifier tracking on parameters
4. Add `va_list` parameter detection
5. Add `Used_Reserved_Field` heuristic
6. Add `StructToUnion` aggregate kind change detection
7. Add preprocessor constant (#define) change tracking (requires separate tool)
8. Add `Removed_Const_Overload` as dedicated source rule
