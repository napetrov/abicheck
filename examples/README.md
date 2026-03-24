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

**69 published cases** (01–68 + 26b):

| Verdict | Count | checker_policy.py set | Icon |
|---------|-------|-----------------------|------|
| BREAKING | 48 | `BREAKING_KINDS` | 🔴 |
| API_BREAK | 2 | `API_BREAK_KINDS` | 🟠 |
| COMPATIBLE_WITH_RISK | 1 | `RISK_KINDS` | 🟡 |
| COMPATIBLE (addition) | 7 | `ADDITION_KINDS` | 🟢 |
| COMPATIBLE (quality) | 9 | `QUALITY_KINDS` | 🟡 |
| NO_CHANGE | 2 | — | ✅ |

> **Verdict source of truth:** [`ground_truth.json`](ground_truth.json), which aligns with
> the 5-tier classification in [`abicheck/checker_policy.py`](../abicheck/checker_policy.py):
> `BREAKING_KINDS` → `API_BREAK_KINDS` → `RISK_KINDS` → `QUALITY_KINDS` → `ADDITION_KINDS`.

| # | Case | Category | abicheck verdict |
|---|------|----------|-----------------|
| [01](case01_symbol_removal/README.md) | Symbol Removal | Breaking | BREAKING 🔴 |
| [02](case02_param_type_change/README.md) | Param Type Change | Breaking | BREAKING 🔴 |
| [03](case03_compat_addition/README.md) | Compat Addition | Addition | COMPATIBLE 🟢 |
| [04](case04_no_change/README.md) | No Change | No Change | NO_CHANGE ✅ |
| [05](case05_soname/README.md) | Soname | Quality | COMPATIBLE 🟡 (bad practice) |
| [06](case06_visibility/README.md) | Visibility | Breaking | BREAKING 🔴 (bad practice) |
| [07](case07_struct_layout/README.md) | Struct Layout | Breaking | BREAKING 🔴 |
| [08](case08_enum_value_change/README.md) | Enum Value Change | Breaking | BREAKING 🔴 |
| [09](case09_cpp_vtable/README.md) | Cpp Vtable | Breaking | BREAKING 🔴 |
| [10](case10_return_type/README.md) | Return Type | Breaking | BREAKING 🔴 |
| [11](case11_global_var_type/README.md) | Global Var Type | Breaking | BREAKING 🔴 |
| [12](case12_function_removed/README.md) | Function Removed | Breaking | BREAKING 🔴 |
| [13](case13_symbol_versioning/README.md) | Symbol Versioning | Quality | COMPATIBLE 🟡 |
| [14](case14_cpp_class_size/README.md) | Cpp Class Size | Breaking | BREAKING 🔴 |
| [15](case15_noexcept_change/README.md) | Noexcept Change | Risk | COMPATIBLE_WITH_RISK 🟡 |
| [16](case16_inline_to_non_inline/README.md) | Inline To Non Inline | Addition | COMPATIBLE 🟢 |
| [17](case17_template_abi/README.md) | Template Abi | Breaking | BREAKING 🔴 |
| [18](case18_dependency_leak/README.md) | Dependency Leak | Breaking | BREAKING 🔴 (bad practice) |
| [19](case19_enum_member_removed/README.md) | Enum Member Removed | Breaking | BREAKING 🔴 |
| [20](case20_enum_member_value_changed/README.md) | Enum Member Value Changed | Breaking | BREAKING 🔴 |
| [21](case21_method_became_static/README.md) | Method Became Static | Breaking | BREAKING 🔴 |
| [22](case22_method_const_changed/README.md) | Method Const Changed | Breaking | BREAKING 🔴 |
| [23](case23_pure_virtual_added/README.md) | Pure Virtual Added | Breaking | BREAKING 🔴 |
| [24](case24_union_field_removed/README.md) | Union Field Removed | Breaking | BREAKING 🔴 |
| [25](case25_enum_member_added/README.md) | Enum Member Added | Addition | COMPATIBLE 🟢 |
| [26](case26_union_field_added/README.md) | Union Field Added | Breaking | BREAKING 🔴 |
| [26b](case26b_union_field_added_compatible/README.md) | Union Field Added Compatible | Addition | COMPATIBLE 🟢 |
| [27](case27_symbol_binding_weakened/README.md) | Symbol Binding Weakened | Quality | COMPATIBLE 🟡 |
| [28](case28_typedef_opaque/README.md) | Typedef Opaque | Breaking | BREAKING 🔴 |
| [29](case29_ifunc_transition/README.md) | Ifunc Transition | Quality | COMPATIBLE 🟡 |
| [30](case30_field_qualifiers/README.md) | Field Qualifiers | Breaking | BREAKING 🔴 |
| [31](case31_enum_rename/README.md) | Enum Rename | API Break | API_BREAK 🟠 |
| [32](case32_param_defaults/README.md) | Param Defaults | No Change | NO_CHANGE ✅ |
| [33](case33_pointer_level/README.md) | Pointer Level | Breaking | BREAKING 🔴 |
| [34](case34_access_level/README.md) | Access Level | API Break | API_BREAK 🟠 |
| [35](case35_field_rename/README.md) | Field Rename | Breaking | BREAKING 🔴 |
| [36](case36_anon_struct/README.md) | Anon Struct | Breaking | BREAKING 🔴 |
| [37](case37_base_class/README.md) | Base Class | Breaking | BREAKING 🔴 |
| [38](case38_virtual_methods/README.md) | Virtual Methods | Breaking | BREAKING 🔴 |
| [39](case39_var_const/README.md) | Var Const | Breaking | BREAKING 🔴 |
| [40](case40_field_layout/README.md) | Field Layout | Breaking | BREAKING 🔴 |
| [41](case41_type_changes/README.md) | Type Changes | Breaking | BREAKING 🔴 |
| [42](case42_type_alignment_changed/README.md) | Type Alignment Changed (alignas) | Breaking | BREAKING 🔴 |
| [43](case43_base_class_member_added/README.md) | Base Class Member Added | Breaking | BREAKING 🔴 |
| [44](case44_cyclic_type_member_added/README.md) | Cyclic Type Member Added | Breaking | BREAKING 🔴 |
| [45](case45_multi_dim_array_change/README.md) | Multi-Dim Array Element Type Change | Breaking | BREAKING 🔴 |
| [46](case46_pointer_chain_type_change/README.md) | Pointer Chain Type Change | Breaking | BREAKING 🔴 |
| [47](case47_inline_to_outlined/README.md) | Inline to Outlined | Addition | COMPATIBLE 🟢 |
| [48](case48_leaf_struct_through_pointer/README.md) | Leaf Struct Change Through Pointer | Breaking | BREAKING 🔴 |
| [49](case49_executable_stack/README.md) | Executable Stack (GNU_STACK RWX) | Quality | COMPATIBLE 🟡 (bad practice) |
| [50](case50_soname_inconsistent/README.md) | SONAME Inconsistent (Wrong Major) | Quality | COMPATIBLE 🟡 (bad practice) |
| [51](case51_protected_visibility/README.md) | Protected Visibility (DEFAULT→PROTECTED) | Quality | COMPATIBLE 🟡 |
| [52](case52_rpath_leak/README.md) | RPATH Leak (Hardcoded Build Dir) | Quality | COMPATIBLE 🟡 (bad practice) |
| [53](case53_namespace_pollution/README.md) | Namespace Pollution (Generic Names) | Breaking | BREAKING 🔴 |
| [54](case54_used_reserved_field/README.md) | Used Reserved Field | Quality | COMPATIBLE 🟡 |
| [55](case55_type_kind_changed/README.md) | Type Kind Changed (struct→union) | Breaking | BREAKING 🔴 |
| [56](case56_struct_packing_changed/README.md) | Struct Packing Changed (pragma pack) | Breaking | BREAKING 🔴 |
| [57](case57_enum_underlying_size_changed/README.md) | Enum Underlying Size Changed | Breaking | BREAKING 🔴 |
| [58](case58_var_removed/README.md) | Global Variable Removed | Breaking | BREAKING 🔴 |
| [59](case59_func_became_inline/README.md) | Function Became Inline (outlined→inline) | Breaking | BREAKING 🔴 |
| [60](case60_base_class_position_changed/README.md) | Base Class Position Changed (MI reorder) | Breaking | BREAKING 🔴 |
| [61](case61_var_added/README.md) | Global Variable Added | Addition | COMPATIBLE 🟢 |
| [62](case62_type_field_added_compatible/README.md) | Type Field Added (Opaque Struct) | Addition | COMPATIBLE 🟢 |
| [63](case63_bitfield_changed/README.md) | Bitfield Width Changed | Breaking | BREAKING 🔴 |
| [64](case64_calling_convention_changed/README.md) | Calling Convention Changed (regcall) | Breaking | BREAKING 🔴 |
| [65](case65_symbol_version_removed/README.md) | Symbol Version Removed (ELF) | Breaking | BREAKING 🔴 |
| [66](case66_language_linkage_changed/README.md) | Language Linkage Changed (extern "C") | Breaking | BREAKING 🔴 |
| [67](case67_tls_var_size_changed/README.md) | TLS Variable Size Changed | Breaking | BREAKING 🔴 |
| [68](case68_virtual_method_added/README.md) | Virtual Method Added (non-virtual → virtual) | Breaking | BREAKING 🔴 |

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

## Benchmark Snapshot (63 cases, 2026-03-17)

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
| TBB | `tbb::task_arena`, `tbb::mutex` | Numeric libraries include these in public headers |
| Boost | `boost::shared_ptr`, `boost::optional` | Layout differs between Boost versions |
| protobuf | `google::protobuf::Message` | Proto3/ABI breakage between major versions |
| libstdc++ | `std::string` (CXX11 ABI) | Changed in GCC 5.x — broke entire ecosystems |
| BLAS/LAPACK | Complex number types, sparse handles | Version-dependent layout |

### Real-world examples

**Numeric libraries** — Public headers that expose `tbb::task_arena` references are
vulnerable when TBB changes `task_arena`'s internal layout between versions (e.g.
TBB 2021.2 → 2021.3). The `.so` files don't change, but consumers break.

**Deep learning frameworks** — Early versions of some DNN libraries exposed internal
implementation types in semi-public headers, requiring major ABI breaks to clean up.

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
