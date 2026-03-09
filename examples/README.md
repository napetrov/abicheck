# ABI Scenario Catalog

An **Application Binary Interface (ABI)** defines the low-level contract between
compiled code: calling conventions, symbol names, type layouts, and vtable structure.
When a shared library changes its ABI without bumping its SONAME, pre-built consumers
crash or silently misbehave. Unlike the source-level API, ABI compatibility is
invisible to the human eye — you need tooling like `abidiff` to catch it.

## Why ABI stability matters

Downstream binaries link against a specific `.so` version at install time. If the
library ships a new build that changes a function signature, removes a symbol, or
alters a struct layout, the binary fails to load or produces wrong results — without
any source change on the consumer side. Linux distributions, language runtimes, and
embedded firmware all depend on ABI stability for safe rolling upgrades.

## abidiff exit-code reference (libabigail 2.4.0)

| Exit | Meaning |
|------|---------|
| 0 | No ABI change |
| 4 | ABI change detected (type/layout diff, addition) |
| 12 | Breaking ABI change (symbol removed) |

> In libabigail 2.4.0, only symbol **removal** triggers exit 12.  
> Type changes, vtable reorderings, and struct growth return exit 4.  
> Both should be treated as breaking by release policy.

---

## Case Index

| # | Case | Category | abicheck verdict | Root cause |
|---|------|----------|-----------------|-----------|
| [01](case01_symbol_removal/README.md) | Symbol Removal | Symbol API | BREAKING 🔴 | Public function deleted from .so |
| [02](case02_param_type_change/README.md) | Parameter Type Change | Symbol API | BREAKING 🟡 | Param type widened, callers pass wrong register |
| [03](case03_compat_addition/README.md) | Compatible Addition | Symbol API | COMPATIBLE 🟢 | New export added, existing callers unaffected |
| [04](case04_no_change/README.md) | No Change | Symbol API | NO_CHANGE ✅ | Identical binary — baseline |
| [05](case05_soname/README.md) | Missing SONAME | ELF/Linker | BAD PRACTICE 🟡 | Library built without -Wl,-soname |
| [06](case06_visibility/README.md) | Visibility Leak | Visibility | BAD PRACTICE 🟡 | Internal symbols unintentionally exported |
| [07](case07_struct_layout/README.md) | Struct Layout Change | Type Layout | BREAKING 🟡 | Field added, sizeof grows, callers undersize |
| [08](case08_enum_value_change/README.md) | Enum Value Change | Type Layout | BREAKING 🟡 | Value inserted mid-enum, existing constants shift |
| [09](case09_cpp_vtable/README.md) | C++ Vtable Change | C++ ABI | BREAKING 🟡 | Virtual method inserted, vtable offsets shift |
| [10](case10_return_type/README.md) | Return Type Change | Symbol API | BREAKING 🟡 | Return type widened, callers read truncated value |
| [11](case11_global_var_type/README.md) | Global Variable Type | Type Layout | BREAKING 🟡 | Global var type widened, symbol size changes |
| [12](case12_function_removed/README.md) | Function Removed | Symbol API | BREAKING 🔴 | Function removed from .so, symbol unresolvable |
| [13](case13_symbol_versioning/README.md) | Symbol Versioning | ELF/Linker | INFORMATIONAL 🟡 | No version script → no `@@VER` on symbols |
| [14](case14_cpp_class_size/README.md) | C++ Class Size Change | C++ ABI | BREAKING 🟡 | Private member grows, sizeof(class) changes |
| [15](case15_noexcept_change/README.md) | noexcept Changed | C++ Source | COMPATIBLE ❌ | Source-level contract; mangling unchanged |
| [16](case16_inline_to_non_inline/README.md) | Inline → Non-inline | C++ ABI | BREAKING ⚠️ | ODR violation; symbol appears in v2 .so |
| [17](case17_template_abi/README.md) | Template Layout Change | C++ ABI | BREAKING 🟡 | Explicit-instantiated template grows in size |
| [18](case18_dependency_leak/README.md) | Dependency ABI Leak | Type Layout | BREAKING ⚠️ | Third-party type in public header changes layout |
| [19](case19_enum_member_removed/README.md) | Enum Member Removed | C API | BREAKING 🔴 | Removing an enum value breaks stored/transmitted integers |
| [20](case20_enum_member_value_changed/README.md) | Enum Value Changed | C API | BREAKING 🔴 | Renumbering enum breaks all consumers using stored values |
| [21](case21_method_became_static/README.md) | Method Became Static | C++ ABI | BREAKING 🔴 | Calling convention mismatch — implicit `this` ignored |
| [22](case22_method_const_changed/README.md) | const Qualifier Changed | C++ ABI | BREAKING 🔴 | `_ZNK...` vs `_ZN...` — different mangled symbol name |
| [23](case23_pure_virtual_added/README.md) | Pure Virtual Added | C++ ABI | BREAKING 🔴 | Existing vtable slot hits `__cxa_pure_virtual` → abort |
| [24](case24_union_field_removed/README.md) | Union Field Removed | C API | BREAKING 🔴 | Field write interpreted as different type — silent wrong data |
| [25](case25_enum_member_added/README.md) | Enum Member Added | C API | COMPATIBLE 🟡 | Adding at end is compatible; older binaries handle known values |
| [26](case26_union_field_added/README.md) | Union Field Added | C API | BREAKING 🔴 | Union grows (4→8 bytes) due to `double` member; TYPE_SIZE_CHANGED |
| [27](case27_symbol_binding_weakened/README.md) | Symbol Binding Weakened | ELF/Linker | COMPATIBLE 🟡 | WEAK symbol can be silently overridden by interposition |
| [28](case28_typedef_opaque/README.md) | Typedef / Opaque Type | Type Layout | BREAKING 🔴 | Typedef base changed, typedef removed, type became opaque |
| [29](case29_ifunc_transition/README.md) | IFUNC Transition | ELF/Linker | COMPATIBLE 🟡 | GNU IFUNC resolves transparently; old `ld.so` may not support |
| [30](case30_field_qualifiers/README.md) | Field Qualifiers | Type Layout | BREAKING 🟡 | Field gained const/volatile — semantic contract change |
| [31](case31_enum_rename/README.md) | Enum Member Rename | C API | BREAKING 🔴 | Old enum names removed from header (source break) |
| [32](case32_param_defaults/README.md) | Parameter Defaults | C++ Source | NO_CHANGE ✅ | Default values are compile-time only — no binary ABI effect |
| [33](case33_pointer_level/README.md) | Pointer Level Change | Symbol API | BREAKING 🔴 | `int*` → `int**` — wrong indirection level causes crash |
| [34](case34_access_level/README.md) | Access Level Change | C++ Source | SOURCE_BREAK 🟡 | `public` → `private` — source break, binary layout unchanged |
| [35](case35_field_rename/README.md) | Field Rename | Type Layout | BREAKING 🟡 | Old field name gone — source break; binary layout unchanged |
| [36](case36_anon_struct/README.md) | Anonymous Struct/Union | Type Layout | BREAKING 🔴 | Anonymous union member type changed → struct size grows |
| [37](case37_base_class/README.md) | Base Class Changes | C++ ABI | BREAKING 🔴 | Base reorder/virtual/added — object layout changes |
| [38](case38_virtual_methods/README.md) | Virtual Method Changes | C++ ABI | BREAKING 🔴 | Virtual added/removed/pure — vtable layout changes |
| [39](case39_var_const/README.md) | Variable Const Change | ELF/Linker | NO_CHANGE ✅ | Const qualifier on globals — not detectable from headers alone |
| [40](case40_field_layout/README.md) | Field Layout Changes | Type Layout | BREAKING 🔴 | Field removed/type changed/offset shifted/bitfield width changed |
| [41](case41_type_changes/README.md) | Type-Level Changes | Type Layout | BREAKING 🔴 | Type removed, alignment changed, sentinel value changed |

---

## Running Consumer App Demos

Every case directory includes an `app.c` or `app.cpp` that demonstrates the
observable impact of the change — which may be runtime breakage, identical
runtime behavior, or a source-only/compile-time failure. The app is compiled
against the **v1 header** and linked to the v1 library, then the v2 library is
swapped in to show the effect.

See the **`## Observed Behavior`** or **`## Real Failure Demo`** section in each
case's README for copy-paste build instructions.

**General pattern:**
```bash
cd examples/caseNN_xxx
# Build v1 library + app (app compiled against v1 header)
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g app.c -I. -L. -lv1 -Wl,-rpath,. -o app
./app          # ← works correctly with v1

# Swap in v2 library (app still uses v1 ABI expectations)
gcc -shared -fPIC -g v2.c -o libv1.so
./app          # ← demonstrates the failure (crash / wrong output / link error)
```

**Severity classification used in Real Failure Demo sections:**
- 🔴 **CRITICAL** — causes crash, wrong output, or silent data corruption
- 🟡 **INFORMATIONAL** — no immediate breakage; compromises future-proofing
- 🟡 **BAD PRACTICE** — library works today but mismanages the ABI contract
- ✅ **BASELINE** — no change; expected passing state

**App demo coverage by case:**

| Cases | App file | Language | Break type |
|-------|---------|----------|------------|
| 01-08, 10-13 | `app.c` | C | Symbol/type/enum/struct breaks |
| 09, 14-17 | `app.cpp` | C++ | Vtable/class/template/noexcept |
| 18 | `app.c` | C | Dependency ABI leak |
| 19-27 | `app.c`/`app.cpp` | C/C++ | Enum/method/union/symbol changes |
| 28, 30-31, 33, 35-36, 39-41 | `app.c` | C | Typedef/qualifier/pointer/layout |
| 32, 34, 37-38 | `app.cpp` | C++ | Defaults/access/base class/virtual |
| 29 | `app.c` | C | IFUNC transition (COMPATIBLE) |

---

## Tool Comparison Matrix

Which tool catches which ABI break? Three modes are compared — see
[`docs/tool_modes.md`](../docs/tool_modes.md) for a full explanation of each mode.

| Case | Description | abidiff+headers | ABICC+headers | ABICC+dump (GCC-only) |
|------|-------------|:---------------:|:-------------:|:----------------------:|
| 01 | Symbol removal | ✅ | ✅ | ✅ |
| 02 | Param type change | ✅ | ✅ | ✅ |
| 03 | Compatible addition | ✅ | ✅ | ✅ |
| 04 | No change | ✅ | ✅ | ✅ |
| 05 | SONAME missing | ❌ | ❌ | ❌ |
| 06 | Visibility leak | ✅ | ❌ | ❌ |
| 07 | Struct layout | ⚠️ | ✅ | ✅ |
| 08 | Enum value | ⚠️ | ✅ | ✅ |
| 09 | vtable change | ⚠️ | ✅ | ✅ |
| 10 | Return type | ⚠️ | ✅ | ✅ |
| 11 | Global var type | ⚠️ | ✅ | ✅ |
| 12 | Function removed | ❌ | ✅ | ❌ |
| 13 | Symbol versioning | ❌ | ❌ | ❌ |
| 14 | Class size | ⚠️ | ✅ | ✅ |
| 15 | noexcept removed | ❌ | ✅ | ❌ |
| 16 | inline→non-inline | ❌ | ✅ | ❌ |
| 17 | Template ABI | ⚠️ | ✅ | ✅ |
| 18 | Dependency leak | ⚠️ | ✅ | ✅ |

**Legend:**
- ✅ = catches the break reliably
- ❌ = misses the break
- ⚠️ = catches only when `.so` compiled with `-g` (DWARF debug info present)
- N/A = not applicable (no meaningful check possible)

> **Cases 05 and 13** are informational/policy issues, not binary breaks — no tool
> treats them as failures by default.

### Column definitions

| Column | Tool | Input | Needs DWARF? | Needs headers? |
|--------|------|-------|:------------:|:--------------:|
| **abidiff+headers** | `abidw --headers-dir` + `abidiff` | two `.so` + include dir | optional | ✅ (required in our pipeline) |
| **ABICC+headers** (= ABICC Usage #2) | `abi-compliance-checker` (headers-only mode) | `.so` + headers | ❌ | ✅ |
| **ABICC+dump** (= ABICC Usage #1) | `abi-compliance-checker` + `abi-dumper` | `.so -g` + headers | ✅ required | ✅ (recommended) |

See [`docs/tool_modes.md`](../docs/tool_modes.md) for detailed explanations,
requirements, limitations, and the combined pipeline decision flowchart.

### Key takeaways

1. **abidiff on stripped `.so`** (no `-g`) degrades to symbol-table-only — misses
   all type layout changes (cases 07–11, 14, 17, 18 become ❌).
2. **ABICC+headers** is the most universally applicable — works on production `.so`,
   catches semantic C++ changes abidiff is blind to (cases 15, 16).
3. **ABICC+dump** is the most accurate when debug `.so` is available — DWARF is the
   ground truth for compiled types; headers can have misleading macros.
4. **Neither tool alone is sufficient** — the `abi-scanner` pipeline runs both
   abidiff and ABICC+headers and uses a worst-of combined verdict.

---

## Quick start

```bash
# Install tools (Ubuntu/Debian)
sudo apt-get install gcc g++ binutils abigail-tools abi-compliance-checker

# Run all integration tests
cd <repo-root>
source venv/bin/activate
pytest tests/test_abi_scenarios.py -v

# Manually explore a case
cd examples/case01_symbol_removal
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so
abidw --headers-dir . --out-file v1.xml libv1.so
abidw --headers-dir . --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
```

---

## Dependency ABI Leaks

A **dependency ABI leak** occurs when your public header `#include`s a type from
a third-party library, and that type's layout changes between versions.

### Why it's insidious

Your library's `.so` file is **byte-for-byte identical**. `nm`, `readelf`, and naive
`abidiff` see nothing suspicious. But callers compiled against the old headers pass
structs of the wrong size, causing heap corruption, stack smashes, or wrong results.

### Common culprits

| Library | Exposed types | Risk |
|---------|--------------|------|
| Intel TBB | `tbb::task_arena`, `tbb::mutex` | oneDAL includes these in public headers |
| Boost | `boost::shared_ptr`, `boost::optional` | Layout differs between Boost versions |
| protobuf | `google::protobuf::Message` | Proto3/ABI breakage between major versions |
| libstdc++ | `std::string` (CXX11 ABI) | Changed in GCC 5.x — broke entire ecosystems |
| Intel MKL | `MKL_Complex8`, sparse handles | Version-dependent layout |

### Intel-specific examples

**oneDAL** — Several oneDAL public headers (e.g. `data_management/data/numeric_table.h`)
expose `tbb::task_arena` references. When Intel TBB changed `task_arena`'s internal
layout in TBB 2021.3, oneDAL's ABI broke for users who had TBB 2021.2 installed.
The `.so` files hadn't changed.

**oneDNN** — Early versions exposed internal `dnnl::impl::*` types in semi-public
headers. This required a major ABI break (`v1.x → v2.x`) to clean up.

### Best practices

1. **Pimpl idiom** — hide implementation details behind a pointer to an incomplete type:
   ```cpp
   // foo.h
   class Foo {
   public:
       Foo();
       ~Foo();
       void run();
   private:
       struct Impl;          // forward declaration only
       Impl* pImpl_;         // no third-party types here
   };
   ```

2. **Opaque C handles** — for C APIs, use typedefs to incomplete structs:
   ```c
   typedef struct foo_context foo_context_t;  // opaque
   foo_context_t* foo_create(void);
   void           foo_destroy(foo_context_t* ctx);
   ```

3. **Version your dependencies** — if you must expose a type, document the exact
   version requirement and check it at CMake configure time.

4. **Use abi-scanner** — run ABICC with `--header-include-path` pointing at all
   transitive dependency headers to detect leaks before release.

See [case18_dependency_leak](case18_dependency_leak/README.md) for a runnable example.


---

## Local Build Comparison & Snapshot Workflow

For comparing locally built libraries against published releases and using
pre-saved ABI snapshots in CI, see **[docs/local_compare.md](../docs/local_compare.md)**.

Quick reference:

```bash
# Compare local build vs published APT package (one-off)
abi-scanner compare \
  apt:intel-oneapi-dnnl=2025.2.0 \
  local:/path/to/libdnnl.so \
  --library-name libdnnl.so --fail-on breaking

# Save ABI baseline for offline use
abi-scanner snapshot apt:intel-oneapi-dnnl=2025.2.0 \
  --output-dir ~/.abi-snapshots/dnnl

# Compare against snapshot (fast, no download)
abi-scanner compare \
  dump:~/.abi-snapshots/dnnl/libdnnl.so-2025.2.0.abi \
  local:/path/to/libdnnl.so --fail-on breaking
```
