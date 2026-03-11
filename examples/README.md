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

> Authoritative expected verdicts for benchmarking are in `examples/ground_truth.json`
> (`expected`, `expected_compat`, `expected_abicc`). If a per-case README text and
> benchmark expectation differ, treat `ground_truth.json` as source of truth.

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
| [13](case13_symbol_versioning/README.md) | Symbol Versioning | ELF/Linker | BREAKING 🔴 | Versioned consumer fails with ld.so assertion when lib loses version script |
| [14](case14_cpp_class_size/README.md) | C++ Class Size Change | C++ ABI | BREAKING 🟡 | Private member grows, sizeof(class) changes |
| [15](case15_noexcept_change/README.md) | noexcept Changed | C++ Source | BREAKING 🔴 | v2 adds throw → GLIBCXX_3.4.21 VERNEED (side-effect break, not mangling) |
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
| [26](case26_union_field_added/README.md) | Union Field Added | C API | BREAKING 🔴 | New field grows sizeof(union) 4→8 bytes; TYPE_SIZE_CHANGED breaks callers |
| [27](case27_symbol_binding_weakened/README.md) | Symbol Binding Weakened | ELF/Linker | COMPATIBLE 🟡 | WEAK symbol can be silently overridden by interposition |
| [29](case29_ifunc_transition/README.md) | IFUNC Transition | ELF/Linker | COMPATIBLE 🟡 | GNU IFUNC resolves transparently; old `ld.so` may not support |

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

## Benchmark Snapshot (42 cases, 2026-03-11)

To avoid drift, this README keeps only a compact summary. Full per-case matrix and
methodology live in docs:
- [`../docs/benchmark_report.md`](../docs/benchmark_report.md)
- [`../docs/tool_comparison.md`](../docs/tool_comparison.md)

| Tool | Correct / Scored | Accuracy |
|------|------------------|----------|
| **abicheck (compare)** | **42/42** | **100%** |
| abicheck (compat) | 40/42 | 95% |
| abicheck (strict, full) | 31/42 | 73% |
| abidiff | 11/42 | 26% |
| abidiff + headers | 11/42 | 26% |
| ABICC (abi-dumper) | 20/30 | 66% (48% effective over 42) |
| ABICC (xml) | 25/41 | 61% |

### Why these numbers differ

- **`compat` < `compare`**: `compat` follows ABICC vocabulary and cannot emit `API_BREAK`
  (`case31`, `case34`), so max is 40/42 in this suite.
- **`strict` can beat ABICC(dump)**: strict intentionally promotes some compatible changes,
  while ABICC(dump) has many ERROR/TIMEOUT cases and only scores on 30/42.
- **`abidiff` == `abidiff+headers` here**: `--headers-dir` only filters public symbols;
  with `-fvisibility=default` in these examples, filtering does not change the set.

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
