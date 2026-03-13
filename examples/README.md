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

> Authoritative expected verdicts for benchmarking are in [`ground_truth.json`](ground_truth.json).
> If a per-case README and benchmark expectation differ, treat [`ground_truth.json`](ground_truth.json) as source of truth.

**48 published cases** (case 42 reserved) — 34 BREAKING 🔴 | 10 COMPATIBLE 🟢 | 2 NO_CHANGE ✅ | 2 API_BREAK 🟠

| # | Case | Category | abicheck verdict |
|---|------|----------|-----------------|
| [01](case01_symbol_removal/README.md) | Symbol Removal | Breaking | BREAKING 🔴 |
| [02](case02_param_type_change/README.md) | Param Type Change | Breaking | BREAKING 🔴 |
| [03](case03_compat_addition/README.md) | Compat Addition | Compatible | COMPATIBLE 🟢 |
| [04](case04_no_change/README.md) | No Change | Compatible | NO_CHANGE ✅ |
| [05](case05_soname/README.md) | Soname | ELF / Policy | COMPATIBLE 🟡 (bad practice) |
| [06](case06_visibility/README.md) | Visibility | ELF / Policy | COMPATIBLE 🟡 (bad practice) |
| [07](case07_struct_layout/README.md) | Struct Layout | Breaking | BREAKING 🔴 |
| [08](case08_enum_value_change/README.md) | Enum Value Change | Breaking | BREAKING 🔴 |
| [09](case09_cpp_vtable/README.md) | Cpp Vtable | Breaking | BREAKING 🔴 |
| [10](case10_return_type/README.md) | Return Type | Breaking | BREAKING 🔴 |
| [11](case11_global_var_type/README.md) | Global Var Type | Breaking | BREAKING 🔴 |
| [12](case12_function_removed/README.md) | Function Removed | Breaking | BREAKING 🔴 |
| [13](case13_symbol_versioning/README.md) | Symbol Versioning | Compatible | COMPATIBLE 🟢 |
| [14](case14_cpp_class_size/README.md) | Cpp Class Size | Breaking | BREAKING 🔴 |
| [15](case15_noexcept_change/README.md) | Noexcept Change | Breaking | BREAKING 🔴 |
| [16](case16_inline_to_non_inline/README.md) | Inline To Non Inline | Compatible | COMPATIBLE 🟢 |
| [17](case17_template_abi/README.md) | Template Abi | Breaking | BREAKING 🔴 |
| [18](case18_dependency_leak/README.md) | Dependency Leak | ELF / Policy | BREAKING 🔴 (bad practice) |
| [19](case19_enum_member_removed/README.md) | Enum Member Removed | Breaking | BREAKING 🔴 |
| [20](case20_enum_member_value_changed/README.md) | Enum Member Value Changed | Breaking | BREAKING 🔴 |
| [21](case21_method_became_static/README.md) | Method Became Static | Breaking | BREAKING 🔴 |
| [22](case22_method_const_changed/README.md) | Method Const Changed | Breaking | BREAKING 🔴 |
| [23](case23_pure_virtual_added/README.md) | Pure Virtual Added | Breaking | BREAKING 🔴 |
| [24](case24_union_field_removed/README.md) | Union Field Removed | Breaking | BREAKING 🔴 |
| [25](case25_enum_member_added/README.md) | Enum Member Added | Compatible | COMPATIBLE 🟢 |
| [26](case26_union_field_added/README.md) | Union Field Added | Breaking | BREAKING 🔴 |
| [26b](case26b_union_field_added_compatible/README.md) | Union Field Added Compatible | Compatible | COMPATIBLE 🟢 |
| [27](case27_symbol_binding_weakened/README.md) | Symbol Binding Weakened | Compatible | COMPATIBLE 🟢 |
| [28](case28_typedef_opaque/README.md) | Typedef Opaque | Breaking | BREAKING 🔴 |
| [29](case29_ifunc_transition/README.md) | Ifunc Transition | Compatible | COMPATIBLE 🟢 |
| [30](case30_field_qualifiers/README.md) | Field Qualifiers | API / Source | BREAKING 🔴 |
| [31](case31_enum_rename/README.md) | Enum Rename | API / Source | API_BREAK 🟠 |
| [32](case32_param_defaults/README.md) | Param Defaults | Compatible | NO_CHANGE ✅ |
| [33](case33_pointer_level/README.md) | Pointer Level | Breaking | BREAKING 🔴 |
| [34](case34_access_level/README.md) | Access Level | API / Source | API_BREAK 🟠 |
| [35](case35_field_rename/README.md) | Field Rename | API / Source | BREAKING 🔴 |
| [36](case36_anon_struct/README.md) | Anon Struct | Breaking | BREAKING 🔴 |
| [37](case37_base_class/README.md) | Base Class | Breaking | BREAKING 🔴 |
| [38](case38_virtual_methods/README.md) | Virtual Methods | Breaking | BREAKING 🔴 |
| [39](case39_var_const/README.md) | Var Const | Breaking | BREAKING 🔴 |
| [40](case40_field_layout/README.md) | Field Layout | Breaking | BREAKING 🔴 |
| [41](case41_type_changes/README.md) | Type Changes | Breaking | BREAKING 🔴 |
| *(42 — reserved, not yet published)* | — | — | — |
| [43](case43_base_class_member_added/README.md) | Base Class Member Added | C++ Layout | BREAKING 🔴 |
| [44](case44_cyclic_type_member_added/README.md) | Cyclic Type Member Added | Struct Layout | BREAKING 🔴 |
| [45](case45_multi_dim_array_change/README.md) | Multi-Dim Array Element Type Change | Struct Layout | BREAKING 🔴 |
| [46](case46_pointer_chain_type_change/README.md) | Pointer Chain Type Change | Function Signature | BREAKING 🔴 |
| [47](case47_inline_to_outlined/README.md) | Inline to Outlined | C++ Symbol | COMPATIBLE 🟢 |
| [48](case48_leaf_struct_through_pointer/README.md) | Leaf Struct Change Through Pointer | Struct Layout | BREAKING 🔴 |

---



## Running Consumer App Demos

Every case directory now includes an `app.c` or `app.cpp` that demonstrates
the exact failure at runtime. See the **`## Real Failure Demo`** section in each
case's README for copy-paste build instructions.

**Severity classification used in Real Failure Demo sections:**
- 🔴 **CRITICAL** — causes crash, wrong output, or silent data corruption
- 🟡 **INFORMATIONAL** — no immediate breakage; compromises future-proofing
- 🟡 **BAD PRACTICE** — library works today but mismanages the ABI contract
- ✅ **BASELINE** — no change; expected passing state

---

## Benchmark Snapshot (48 cases, 2026-03-11)

To avoid drift, this README keeps only a compact summary. Full per-case matrix and
methodology live in docs:
- [`../docs/benchmark_report.md`](../docs/benchmark_report.md)
- [`../docs/tool_comparison.md`](../docs/tool_comparison.md)

| Tool | Correct / Scored | Accuracy |
|------|------------------|----------|
| **abicheck (compare)** | **48/48** | **100%** |
| abicheck (compat) | 46/48 | 96% |
| abidiff | 12/48 | 25% |
| abidiff + headers | 12/48 | 25% |
| ABICC (xml) | 30/47 | 63% (1 timeout, 48 cases attempted) |
| ABICC (abi-dumper) | 24/48 | 50% (12 error/timeout) |

### Why these numbers differ

- **`compat` < `compare`**: `compat` follows ABICC vocabulary and cannot emit `API_BREAK`
  (`case31`, `case34`), so max is 46/48 in this suite.
- **`abidiff` == `abidiff+headers` here**: `--headers-dir` only filters public symbols;
  with `-fvisibility=default` in these examples, filtering does not change the set.
- **ABICC(dumper)** missed case43 (base class member added) — classified as COMPATIBLE.
  Reason: ABICC focuses on exported symbols, not derived class layout shifts.

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

4. **Use abicheck** — run `abicheck dump` with all transitive dependency headers
   to detect leaks before release.

See [case18_dependency_leak](case18_dependency_leak/README.md) for a runnable example.


---

## Local Build Comparison & Snapshot Workflow

For comparing locally built libraries against published releases and using
pre-saved ABI snapshots in CI, see **[docs/local_compare.md](../docs/local_compare.md)**.
