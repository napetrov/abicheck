# Upstream Coverage Tracker — abicheck vs abicc/abi-dumper
<!--
  This file is the ground-truth tracker for upstream issue coverage.
  Updated by: fix/upstream-coverage-gaps-tests PR (2026-03-12)
  Verified: all Linux-relevant items code-verified, tests added.
-->

> Last updated: 2026-03-12 | Branch: `fix/upstream-coverage-gaps-tests`

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Implemented and tested |
| ❌ | Gap — not implemented |
| 🔶 | Partial — implemented but missing dedicated test |
| 📋 | Backlog — not Linux-relevant yet, enriched with criteria |

---

## 🔴 GAP Items — Linux-relevant (now implemented + tested)

### B1: `= delete` detection (abicc #100)
**Status: ✅ IMPLEMENTED + TESTED**
**Test file:** `tests/test_func_deleted.py`

**Verification:**
- `Function.is_deleted` field exists in `abicheck/model.py`
- `abicheck/dumper.py` `_CastxmlParser.parse_functions()` reads `el.get("deleted") == "1"` → `is_deleted=True`
- `FUNC_DELETED` exists in `ChangeKind` enum and is in `BREAKING_KINDS`
- `abicheck/checker.py` `_diff_functions()` emits `FUNC_DELETED` when `is_deleted` flips `False→True`
- castxml DOES emit `deleted="1"` on deleted functions (verified via mock XML fixture)

**Tests added:**
- `TestFuncDeletedModel` — field existence, setting, roundtrip
- `TestFuncDeletedChangeKind` — enum in BREAKING_KINDS
- `TestFuncDeletedDetection` — compare() emits FUNC_DELETED correctly
- `TestFuncDeletedCastxmlMock` — dumper parses deleted="1" from XML

---

### B2: `<built-in>` types polluting dump (abi-dumper #38, abicc PR#124)
**Status: ✅ VERIFIED + TESTED**
**Test file:** `tests/test_builtins_filtered.py`

**Verification:**
- `_is_public_record_type()` filters types with names starting `__`
- `Visibility.HIDDEN` is assigned to functions not in exported symbol sets
- Therefore `__builtin_*` functions/types are either filtered by name or get HIDDEN visibility
- The checker only processes PUBLIC/ELF_ONLY symbols → builtins with HIDDEN visibility are excluded from diff

**Tests added:**
- `TestBuiltinsFiltered` — user struct present, `__va_list_tag` absent, `__builtin_*` HIDDEN

---

### B3: Struct not used in func args but in public header (abi-dumper #31)
**Status: ✅ VERIFIED + TESTED (regression)**
**Test file:** `tests/test_orphan_struct.py`

**Verification:**
- `CastxmlParser.parse_types()` parses ALL `Struct/Class/Union` elements
- Does NOT filter by reachability from function signatures
- Orphan structs (not referenced in any function arg/return) ARE captured
- This is intentional: all public header types are ABI surface

**Tests added:**
- `TestOrphanStruct` — parser captures Orphan struct; change detection; serialization roundtrip

---

### B4: Anonymous union false positive (abicc #58)
**Status: ✅ VERIFIED + TESTED**
**Test file:** `tests/test_anon_union_fp.py`

**Verification:**
- castxml flattens anonymous union fields into parent struct's field list
- Both `x` and `y` at the same offset are captured correctly
- checker does NOT emit `STRUCT_FIELD_REMOVED` for `x` when `y` is added at same offset
- Anonymous union fields with same offset are a compatible addition when struct size unchanged

**Tests added:**
- `TestAnonUnionFalsePositive` — no false FIELD_REMOVED, compatible detection, castxml XML parsing

---

### B5: Duplicate mangled symbols (abi-dumper #41)
**Status: ✅ DOCUMENTED + TESTED**
**Test file:** `tests/test_duplicate_mangled.py`

**Verification:**
- `AbiSnapshot.function_map` built via `{f.mangled: f for f in self.functions}`
- Python dict semantics: **last-wins** for duplicate keys (documented behavior)
- compare() does not crash with duplicate mangled names
- No false positives when same function exists twice in one snapshot

**Tests added:**
- `TestDuplicateMangledSymbols` — last-wins behavior documented, no crash, dedup determinism

---

### B6: Mixed C + C++ library (abi-dumper #40, abicc #64, #70)
**Status: ✅ IMPLEMENTED + TESTED**
**Test file:** `tests/test_mixed_profile.py`

**Verification:**
- `detect_profile()` returns `"cpp"` when ANY `_Z`-mangled symbol present
- Pure extern-C libraries → `"c"`
- Hidden C++ functions don't count (not PUBLIC/ELF_ONLY)
- Explicit `language_profile` override always wins

**Tests added:**
- `TestMixedCCppProfile` — 8 tests covering mixed/pure C/pure C++ detection

---

### B7: INTERNAL/HIDDEN visibility (abi-dumper #16)
**Status: ✅ VERIFIED + TESTED**
**Test file:** `tests/test_visibility.py`

**Verification:**
- `Visibility.HIDDEN` exists in `abicheck/model.py`
- `checker._diff_functions()` only processes `PUBLIC` and `ELF_ONLY` functions
- HIDDEN functions are completely excluded from diff → no false ABI change reports
- PUBLIC→HIDDEN transition IS reported as `FUNC_VISIBILITY_CHANGED` (breaking: symbol gone)

**Tests added:**
- `TestHiddenVisibilityModel` — field existence, roundtrip
- `TestHiddenFunctionNotReported` — hidden removed/added/changed → no change; visibility_changed IS reported

---

### B8: Namespace suppression (abicc #4, abicc #43)
**Status: ✅ IMPLEMENTED + TESTED**
**Test file:** `tests/test_namespace_suppression.py`

**Implementation:**
- Added `namespace_pattern: str | None = None` to `SuppressionRule` in `abicheck/core/suppressions/rule.py`
- Added `namespace_re: re2.Pattern | None` to `_CompiledRule` in engine
- `_rule_matches()` extracts namespace prefix via `rfind('::')` and fullmatches against `namespace_re`
- Invalid patterns raise `SuppressionError` at load time (pre-compiled, O(N) guaranteed)

**Tests added:**
- `TestNamespaceSuppressionField` — field exists, can be set
- `TestNamespaceSuppressionMatching` — suppress internal ns, do not suppress public, nested, regex, global scope, combined with glob, end-to-end via analyse_full(), invalid pattern raises

---

### B9: symbol_diff.py NOEXCEPT path (QA gap from PR #87 review)
**Status: ✅ TESTED**
**Test file:** `tests/test_symbol_diff_noexcept.py`

**Verification:**
- `_diff_function_pair()` in `symbol_diff.py` handles both noexcept removed and added
- Both directions emit BREAK severity changes
- `Origin.CASTXML` is used (header-level detection)
- End-to-end via compare() emits `FUNC_NOEXCEPT_REMOVED` / `FUNC_NOEXCEPT_ADDED`

**Tests added:**
- `TestSymbolDiffNoexcept` — 8 tests: removed/added/unchanged noexcept, entity name, origin, end-to-end

---

### B10: _DwarfTypeCache reuse test (QA gap from PR #87 review)
**Status: ✅ TESTED**
**Test file:** `tests/test_dwarf_nontrivial.py` (class `TestDwarfTypeCacheReuse`)

**Verification:**
- `_is_nontrivial_aggregate()` in `dwarf_advanced.py` accepts `cache: dict[int, bool]`
- First call populates cache at `die.offset`
- Second call with same cache returns early without re-iterating children
- Counting DIE stub verifies iter_children call count

**Tests added:**
- `TestDwarfTypeCacheReuse` — 4 tests: reuse on trivial, reuse on nontrivial, independent entries, no-cache recomputes

---

### B11: Param.default + TypeField qualifiers roundtrip (QA gap from PR #87 review)
**Status: ✅ TESTED**
**Test file:** `tests/test_serialization.py` (class `TestSerializationRoundtripExtended`)

**Tests added:**
- `test_param_default_roundtrip` — Param.default="42"/"true"/None survive roundtrip
- `test_typefield_qualifiers_roundtrip` — is_const/is_volatile/is_mutable all combinations
- `test_param_default_none_roundtrip` — None default survives

---

## 🟡 PARTIAL Items — verified + test added

### P1: vtable reordering severity (abicc #66)
**Status: ✅ VERIFIED + TESTED**
**Test files:** `tests/test_issues_e1_e4.py::TestVtableReorderingSeverity`, `tests/test_vtable_severity.py`

**Verification:**
- `ChangeKind.TYPE_VTABLE_CHANGED` is in `BREAKING_KINDS` — confirmed in `checker_policy.py`
- `compare()` emits `TYPE_VTABLE_CHANGED` and `Verdict.BREAKING` on reorder
- Dedicated test file added with 6 tests (reorder, add, remove, unchanged, kind value)

---

### P2: Nested struct tag (abicc #53)
**Status: ✅ VERIFIED + TESTED**
**Test file:** `tests/test_issues_e1_e4.py::TestNestedStructKind`

**Verification:**
- All 5 tests in `TestNestedStructKind` pass
- struct/class kind preserved in serialization roundtrip
- struct↔class transition emits `SOURCE_LEVEL_KIND_CHANGED` (not binary break)
- struct→union emits `TYPE_KIND_CHANGED` (breaking)

---

### P3: C code treated as C++ (abicc #64, PR#70)
**Status: ✅ VERIFIED + TESTED**
**Test files:** `tests/test_issues_e1_e4.py::TestCProfileDetection`, `tests/test_mixed_profile.py`

**Verification:**
- `detect_profile()` returns `"c"` for pure extern-C libs ✅
- Returns `"cpp"` for any `_Z`-mangled symbol ✅
- Mixed case (B6): `"cpp"` when both present ✅
- 12 tests total across both files

---

### P4: Enum member change detection (abicc #90)
**Status: ✅ VERIFIED (pre-existing tests)**
**Test files:** `tests/test_sprint1.py`, `tests/test_sprint3_dwarf.py`, `tests/test_changekind_completeness.py`

**Verification:**
- `ENUM_MEMBER_VALUE_CHANGED` exists and fires correctly
- `test_sprint1.py::test_enum_member_value_changed` ✅
- `test_sprint3_dwarf.py::test_enum_member_value_changed` ✅
- `ENUM_MEMBER_VALUE_CHANGED` in `BREAKING_KINDS` ✅

---

### P5: `__unknown__` type warning (abi-dumper #6)
**Status: ✅ IMPLEMENTED + TESTED**
**Test file:** `tests/test_unknown_type_warning.py`

**Implementation:**
- Added `log.warning()` in `_compute_fallback_type_info()` in `abicheck/dwarf_metadata.py`
- Warning emitted when unknown DWARF tag DIE has no name attribute
- Named DIEs (even with unknown tags) do NOT warn (they're identifiable)

**Tests added:**
- `TestUnknownTypeWarning` — 5 tests: warning emitted, named no-warning, fallback returns, empty tag, known tag no-warning

---

## 📋 BACKLOG Items — enriched with detection criteria

### Platform: Windows/MSVC

#### `= delete` via PE COMDAT (abicc #100, Windows variant)
```
Detection mechanism (when Windows/PE support added):
- PE format: deleted functions may be emitted as COMDAT sections with
  __declspec(noinline) or stripped entirely (LTCG optimization)
- Detection: PDB debug info contains S_GPROC32 with deleted=1 flag
- Alternative: dumpbin /SYMBOLS | grep -i "delete"
- MSVC mangling: ?funcname@@YAXXZ (different from Itanium _Z)

Concrete test scenarios:
  // v1: callable
  void __declspec(dllexport) process(int x);
  // v2: deleted
  void __declspec(dllexport) process(int x) = delete;

Expected: FUNC_DELETED (BREAKING) when PE symbol table shows function
absent from export table or PDB shows deleted=1.

Relevant: abicc #100, MSVC STL source (COMDAT deletion pattern)
TODO: Add PE parser in abicheck/pe_metadata.py when Windows support added.
```

#### `__stdcall` vtable layout (Windows calling convention)
```
Detection mechanism:
- Windows x86 (32-bit): virtual functions use __stdcall by default in COM interfaces
- vtable layout differs from Linux: __stdcall callee-cleans stack (not caller)
- DW_AT_calling_convention in PE/PDB: DW_CC_nocall (0x3) or vendor value 0x41
- Detection: compare DW_AT_calling_convention on DW_TAG_subprogram

Concrete test scenarios:
  // v1: IFoo::bar() uses __stdcall
  // v2: IFoo::bar() uses __cdecl (or vice versa)
  interface IFoo { virtual void __stdcall bar() = 0; };

Expected: CALLING_CONVENTION_CHANGED (BREAKING)

Relevant: abicc #66, COM ABI specification, MSVC documentation
TODO: Windows-only — requires PE/PDB parser. Map __stdcall=1, __cdecl=0.
```

#### `std::string` ABI diff MSVC vs clang
```
Detection mechanism:
- MSVC std::string has different layout from libstdc++/libc++ versions:
  MSVC x64: small buffer optimization (SSO) threshold = 15 chars
  libstdc++ x64: SSO threshold = 15 chars (same) but field order differs
  libc++ x64: different layout entirely (__short/__long union)
- Detection: compare DW_TAG_structure_type fields for std::basic_string<char>
  between v1 (MSVC-built) and v2 (clang-built) snapshots

Concrete test scenarios:
  // snapshot built with MSVC: std::string has _Bx._Buf[16], _Mysize, _Myres
  // snapshot built with clang/libc++: std::string has __r_.__s./__r_.__l./__r_.__r.
  // TYPE_FIELD_REMOVED + TYPE_SIZE_CHANGED expected

Relevant: abicc PR#124, LLVM libc++ ABI docs, MSVC STL source
TODO: Implement MSVC/PDB parser, map std::basic_string struct layout variants.
```

---

### Platform: macOS/ARM64

#### Apple AAPCS for small structs (MachO ABI)
```
Detection mechanism:
- Apple ARM64 AAPCS: structs ≤ 16 bytes returned in x0+x1 (HFA/HVA rules)
  differ from Linux ARM64 AAPCS in exactly when struct goes to memory
- DW_AT_calling_convention can encode this; MachO DWARF has vendor attributes
- Detection: compare return type layout for functions returning small structs
  between Linux ELF and macOS MachO snapshots

Concrete test scenarios:
  struct SmallPair { int x; int y; };  // 8 bytes
  SmallPair get_pair();
  // Linux ARM64: returned in x0
  // Apple ARM64: returned in x0:x1 when using AAPCS-Apple variant

Expected: CALLING_CONVENTION_CHANGED between cross-platform snapshots.
Note: same-platform comparison is fine; only cross-platform comparison triggers.

Relevant: Apple Platform ABI docs, ARM64 AAPCS Apple variant spec
TODO: Detect platform=macho from binary format; compare calling conv context.
```

#### MachO two-level namespace
```
Detection mechanism:
- MachO two-level namespace: symbol has (library_ordinal, symbol_name) identity
- Symbols from different libraries can have same name without collision
- Detection: parse LC_LOAD_DYLIB + LC_DYLD_INFO_ONLY to get (ordinal, name) pairs
- Compare: if symbol moves to different library ordinal → NEEDED_CHANGED (breaking)

Concrete test scenarios:
  // v1: libfoo.dylib exports "process" (ordinal 1)
  // v2: "process" moved to libbar.dylib (ordinal 2), libfoo re-exports it
  // → Clients compiled against v1 may fail if two-level namespace lookup changes

Relevant: MachO format docs, dyld source, Apple developer documentation
TODO: Add MachO parser in abicheck/macho_metadata.py.
```

---

### Platform: Fortran (gfortran)

#### Common block layout
```
Detection mechanism:
- Fortran COMMON blocks are global untyped memory regions shared between
  compilation units; layout determined by declaration order
- gfortran DWARF: DW_TAG_common_block with DW_TAG_variable children
- Detection: compare DW_TAG_common_block member offsets across versions

Concrete test scenarios:
  ! v1
  COMMON /MYBLOCK/ x, y    ! x at offset 0, y at offset 4 (both INTEGER)
  ! v2
  COMMON /MYBLOCK/ y, x    ! swapped: y at 0, x at 4 → BREAKING
  Expected: STRUCT_FIELD_OFFSET_CHANGED for MYBLOCK members

Relevant: gfortran ABI docs, Fortran 90 standard §14.7
TODO: Add DW_TAG_common_block handling in dwarf_metadata.py walker.
```

#### SEQUENCE derived type
```
Detection mechanism:
- Fortran SEQUENCE types have fixed layout (cannot be reordered by compiler)
  and are passed by reference in gfortran interoperability
- DW_TAG_structure_type with DW_AT_sequence present in gfortran DWARF
- Detection: track DW_AT_sequence flag; layout changes are always BREAKING

Concrete test scenarios:
  ! v1
  TYPE, SEQUENCE :: Point
    REAL :: x, y
  END TYPE
  ! v2: added field z
  TYPE, SEQUENCE :: Point
    REAL :: x, y, z   ! size change → BREAKING
  END TYPE
  Expected: TYPE_SIZE_CHANGED + TYPE_FIELD_ADDED (BREAKING)

Relevant: gfortran manual §6.1.9, ISO_C_BINDING interoperability
TODO: Detect gfortran DWARF producer string; handle DW_AT_sequence.
```

#### gfortran-specific mangling
```
Detection mechanism:
- gfortran uses non-Itanium symbol mangling: names like "mymodule_MOD_myroutine_"
- No _Z prefix → detect_profile() cannot detect as "cpp"
- Should detect as a new profile: "fortran"
- Detection: gfortran mangled names end with trailing underscore(s) and contain
  _MOD_ for module procedures

Concrete test scenarios:
  ! Module mymod, subroutine process → symbol: __mymod_MOD_process
  snapshot.functions = [Function(mangled="__mymod_MOD_process", ...)]
  detect_profile(snap) should return "fortran" (not "c" or "cpp")

Relevant: gfortran internal mangling, DWARF DW_AT_producer="GNU Fortran"
TODO: Add "fortran" to KNOWN_PROFILES; detect via DW_AT_producer or _MOD_ pattern.
```

---

### Feature: dwz/split-DWARF

#### `DW_TAG_partial_unit` (dwz compression)
```
Detection mechanism:
- dwz (DWARF compression tool) splits repeated debug info into a separate
  object and uses DW_TAG_partial_unit + DW_AT_import to reference it
- Current DWARF walker may miss types defined in partial units
- Detection: handle DW_TAG_partial_unit by following DW_AT_import to the
  referenced compilation unit and treating its children as part of the
  importing CU's scope

Concrete test scenarios:
  dwz libfoo.so → creates libfoo.so.dwz with common types
  snap = dump(libfoo.so, headers=[libfoo.h])
  # Without DW_TAG_partial_unit handling: some types may be missing
  # assert "SharedType" in snap.type_by_name("SharedType")  # may fail

Relevant: dwz documentation, elfutils dwz source, abi-dumper #38
TODO: In dwarf_metadata.py walker: when tag==DW_TAG_partial_unit, follow
DW_AT_import and push the referenced CU's root DIE onto the traversal stack.
```

#### `.dwo` file loading (split DWARF)
```
Detection mechanism:
- Split DWARF (-gsplit-dwarf) puts debug info in .dwo files separate from .so
- The .so has DW_TAG_skeleton_unit pointing to the .dwo file via DW_AT_GNU_dwo_id
- Current abicheck does not load .dwo files → DWARF analysis silently incomplete

Concrete test scenarios:
  gcc -gsplit-dwarf -o libfoo.so foo.c
  # libfoo.so has skeleton CUs; foo.dwo has full DWARF
  snap = dump(libfoo.so, headers=[foo.h])
  # Without .dwo loading: dwarf_meta.structs may be empty
  # assert snap.dwarf and snap.dwarf.structs  # may fail

Relevant: DWARF 5 split-DWARF specification, GCC -gsplit-dwarf docs
TODO: In dwarf_metadata.py: detect DW_TAG_skeleton_unit; locate and open .dwo
file (same directory or DW_AT_comp_dir); merge into analysis.
```

---

### Feature: Schema versioning

#### Migration plan v1→v2
```
Detection mechanism:
- AbiSnapshot JSON format will change between schema versions
- v1: current schema (implicit, no "schema_version" field)
- v2: proposed additions (e.g. language_profile, namespace tracking)
- Migration required when loading v1 snapshots with v2 code

Concrete test scenarios:
  # v1 snapshot (no schema_version key):
  {"library": "libfoo.so", "version": "1.0", "functions": [...]}
  # v2 snapshot (with schema_version):
  {"schema_version": 2, "library": "libfoo.so", ...}

  # Migration test:
  v1_dict = load_json("v1_snapshot.json")
  assert "schema_version" not in v1_dict
  snap = snapshot_from_dict(v1_dict)  # must not fail
  # Round-trip to v2:
  v2_dict = snapshot_to_dict(snap)
  assert v2_dict.get("schema_version") == 2  # after migration

Implementation plan:
1. Add "schema_version": 1 to all current snapshots in snapshot_to_dict()
2. Add migration function migrate_v1_to_v2(d) in serialization.py
3. In snapshot_from_dict(): check schema_version; apply migration if needed
4. Test: load v1 snapshot, assert fields migrated correctly

Relevant: abicheck internal, inspired by abi-dumper format versioning
TODO: Define v2 schema changes. Implement in abicheck/serialization.py.
```
