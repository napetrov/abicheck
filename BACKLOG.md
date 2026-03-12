# abicheck — Gap & Platform Backlog

Items that are known gaps or require future platform support.
Each item includes the upstream reference and concrete detection criteria.

---

## ❌ Open Gaps (Linux, needs implementation)

### `= delete` ELF fallback
- **Upstream:** lvc/abi-compliance-checker #100
- **Status:** castxml path works (`deleted="1"` attribute). ELF fallback for pre-castxml binaries missing.
- **Detection:** ELF: symbol present in v1 but marked with a `@@DELETED` or absent from `dynsym` in v2.
- **Test scenario:** compile `void f();` → `void f() = delete;`, verify `FUNC_DELETED` fires.

### Template inner-type analysis (`std::vector<T>`)
- **Upstream:** lvc/abi-compliance-checker #38, #73
- **Status:** outer type name diff works; inner `T` change not detected.
- **Detection:** castxml XML walk: `<TemplateArgument>` → resolve inner type → compare layout.
- **Test scenario:** `struct S { int x; };` → `struct S { int x; double y; };` used as `std::vector<S>` param. Assert `TYPE_SIZE_CHANGED` propagates to param change.

### dwz / split-DWARF
- **Upstream:** lvc/abi-dumper #35, PR #43
- **Status:** `DW_TAG_partial_unit` / `.dwo` / `.dwp` not followed by our DWARF walker.
- **Detection:** pyelftools 0.30+ supports DWARF5. Need `DW_TAG_imported_unit` → load supplementary object.
- **Test scenario:** build lib with `dwz` compression, run dump, assert symbol count matches non-compressed.

### Private symbol shadowing
- **Upstream:** lvc/abi-dumper #22
- **Status:** private TU symbols with same name as public API can contaminate snapshot.
- **Detection:** cross-reference ELF `dynsym` (public) vs castxml header scope.
- **Test scenario:** lib with `public/foo.h: int f();` and `private/impl.cc: static int f()`. Assert only public `f` in snapshot.

### Duplicate mangled symbol determinism
- **Upstream:** lvc/abi-dumper #41
- **Status:** last-wins (dict overwrite). No guarantee across TUs.
- **Detection:** canonical merge strategy (e.g. prefer non-weak symbol, or first-seen).
- **Test scenario:** two TUs define `int f(int)` with different return types; assert snapshot is deterministic across parse order.

---

## 📋 Platform Backlog

### Windows / MSVC
- **Upstream:** lvc/abi-compliance-checker #9, #50, #56, #121; lvc/abi-dumper #8
- **Needed:**
  - PE format detection (`platform == "pe"`)
  - `__stdcall` / `__cdecl` calling convention in value-ABI traits
  - MSVC vtable layout (thunks differ from Itanium)
  - `std::string` ABI diff MSVC vs clang (SSO layout differs)
  - castxml with `cl.exe` backend
- **Test scenarios:**
  - `__stdcall` function signature change → `VALUE_ABI_TRAIT_CHANGED`
  - MSVC vtable thunk addition → `TYPE_VTABLE_CHANGED`

### macOS / ARM64
- **Upstream:** lvc/abi-compliance-checker #116, #119; lvc/abi-dumper #9
- **Needed:**
  - MachO format detection (`platform == "macho"`)
  - Apple AAPCS: structs ≤16 bytes returned in x0+x1 vs memory → calling convention trait
  - Two-level namespace: `LC_LOAD_DYLIB` vs ELF `DT_NEEDED`
  - `install_name` as SONAME equivalent
- **Test scenarios:**
  - Struct grows from 12 → 20 bytes → calling convention changes from register to memory → `VALUE_ABI_TRAIT_CHANGED`

### Fortran
- **Upstream:** lvc/abi-compliance-checker #11, #92
- **Needed:**
  - gfortran mangling (`__module_MOD_func`)
  - DWARF walk for Fortran (`DW_TAG_subprogram` + `DW_AT_linkage_name`)
  - `.mod` file parsing for derived types / interfaces
  - `SEQUENCE` derived type → fixed layout (like C struct)
  - Common block layout (global shared memory)
- **Test scenarios:**
  - Fortran `INTEGER FUNCTION f(x)` signature change → `FUNC_PARAMS_CHANGED`
  - `SEQUENCE` type field reorder → `TYPE_FIELD_REORDERED`

### New Compilers / Standards
- **Clang multi-backend:** explicit `--compiler clang/gcc` flag for castxml invocation (lvc/abi-compliance-checker #110)
- **GCC 15+:** `bool` as reserved keyword in C23 — verify C test fixtures compile clean
- **C++23/26:** `std::expected`, `std::mdspan` as parameter types — template analysis needed

---

## 🟡 UX / DX Backlog

- `--verbose` / `--debug` flag (lvc/abi-compliance-checker #45, #65)
- `--no-color` for CI environments
- castxml stderr not suppressed in verbose mode
- Distinct exit code for "compilation failed" (currently = 2 = validation error)
- Type size table in report (lvc/abi-compliance-checker #115)
- Progress output for large libraries (lvc/abi-dumper #20)
