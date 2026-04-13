# ABI Cheat Sheet

Quick-reference card for shared-library maintainers. Scannable in 2 minutes.

For deeper explanations see [ABI Breaks Explained](abi-breaks-explained.md) and [Verdicts](verdicts.md).

---

## Safe Changes (COMPATIBLE)

These changes preserve binary compatibility. Existing consumers continue to work without recompilation.

| Change | Why Safe | Example |
|--------|----------|---------|
| Add new exported function | Existing binaries never reference it; linker ignores unknown symbols | [case03](https://github.com/napetrov/abicheck/tree/main/examples/case03_compat_addition) |
| Append enum member (end, no value shift) | Compiled binaries use integer values; existing values unchanged | [case25](https://github.com/napetrov/abicheck/tree/main/examples/case25_enum_member_added) |
| Add union field without growing size | Union size = max(fields); fits within existing allocation | [case26b](https://github.com/napetrov/abicheck/tree/main/examples/case26b_union_field_added_compatible) |
| Weaken symbol binding (GLOBAL to WEAK) | Symbol still resolves; interposition semantics relax | [case27](https://github.com/napetrov/abicheck/tree/main/examples/case27_symbol_binding_weakened) |
| Add IFUNC dispatch | Transparent to callers; resolver picks implementation at load time | [case29](https://github.com/napetrov/abicheck/tree/main/examples/case29_ifunc_transition) |
| Outline an inline function (add export) | New symbol appears; callers with inlined copy still work | [case47](https://github.com/napetrov/abicheck/tree/main/examples/case47_inline_to_outlined) |
| Add new global variable | No existing code references it | [case61](https://github.com/napetrov/abicheck/tree/main/examples/case61_var_added) |
| Add field to opaque struct | Callers access through pointers only; layout is hidden | [case62](https://github.com/napetrov/abicheck/tree/main/examples/case62_type_field_added_compatible) |

---

## Breaking Changes (NEVER do in a minor release)

These cause crashes, wrong results, or link failures in pre-compiled consumers.

| Change | What Happens at Runtime | Example |
|--------|------------------------|---------|
| Remove exported symbol | `undefined symbol` on dlopen/startup | [case01](https://github.com/napetrov/abicheck/tree/main/examples/case01_symbol_removal) |
| Change parameter types | Caller passes args in wrong registers/format; garbage or crash | [case02](https://github.com/napetrov/abicheck/tree/main/examples/case02_param_type_change) |
| Change struct layout/size | Stack corruption; reads/writes past allocation boundary | [case07](https://github.com/napetrov/abicheck/tree/main/examples/case07_struct_layout) |
| Change enum member values | Switch/lookup tables use stale integer values; wrong branch taken | [case08](https://github.com/napetrov/abicheck/tree/main/examples/case08_enum_value_change) |
| Reorder virtual methods | Vtable slot mismatch; call dispatches to wrong method silently | [case09](https://github.com/napetrov/abicheck/tree/main/examples/case09_cpp_vtable) |
| Change return type | Caller interprets return register/memory as wrong type | [case10](https://github.com/napetrov/abicheck/tree/main/examples/case10_return_type) |
| Change class size (add members) | `new`/stack allocation undersized; heap corruption, SIGSEGV | [case14](https://github.com/napetrov/abicheck/tree/main/examples/case14_cpp_class_size) |
| Remove enum member | Code referencing removed constant fails at compile time or uses stale value | [case19](https://github.com/napetrov/abicheck/tree/main/examples/case19_enum_member_removed) |
| Change type alignment (`alignas`) | Misaligned access; SIGBUS on strict-alignment architectures | [case42](https://github.com/napetrov/abicheck/tree/main/examples/case42_type_alignment_changed) |
| Change struct packing (`pragma pack`) | Field offsets shift; every member read is wrong | [case56](https://github.com/napetrov/abicheck/tree/main/examples/case56_struct_packing_changed) |
| Change calling convention | Parameters read from wrong registers; total data corruption | [case64](https://github.com/napetrov/abicheck/tree/main/examples/case64_calling_convention_changed) |
| Remove symbol version node | Dynamic linker refuses to load; `version 'FOO_1.0' not found` | [case65](https://github.com/napetrov/abicheck/tree/main/examples/case65_symbol_version_removed) |

See the full breaking catalog in [Breaking Cases Catalog](breaking-cases-catalog.md).

---

## Source-Only Breaks (API_BREAK)

Binary-compatible, but recompilation against new headers fails. Verdict: 🟠 API_BREAK.

| Change | Impact | Example |
|--------|--------|---------|
| Rename enum member (same value) | `LOG_ERR` no longer compiles; binary still uses integer `1` | [case31](https://github.com/napetrov/abicheck/tree/main/examples/case31_enum_rename) |
| Narrow access level (public to private) | Downstream code calling `helper()` gets compile error | [case34](https://github.com/napetrov/abicheck/tree/main/examples/case34_access_level) |
| Remove default parameter | Call sites relying on default fail to compile; ABI unchanged | -- |

---

## Risk Changes (deployment concern)

Binary-compatible, but may break at deployment time. Verdict: 🟡 COMPATIBLE_WITH_RISK.

| Change | Risk | Example |
|--------|------|---------|
| New GLIBC/GLIBCXX version requirement | Binaries won't load on older distros missing the required symbol version | -- (detected via `SYMBOL_VERSION_REQUIRED_ADDED`) |
| Leaked dependency symbol changed | Transitive dependency update shifts symbols your consumers never directly linked | -- |
| `noexcept` removed | C++17 callers compiled with `noexcept` in function type get UB on throw | [case15](https://github.com/napetrov/abicheck/tree/main/examples/case15_noexcept_change) |

---

## Quality Warnings

No immediate breakage, but these compromise the ABI contract or security posture. abicheck flags these as 🟡 COMPATIBLE quality checks (`SONAME_MISSING`, `VISIBILITY_LEAK`, `EXECUTABLE_STACK`, `RPATH_CHANGED`). Fixing them later often causes 🔴 BREAKING changes.

| Warning | Why It Matters | Example |
|---------|---------------|---------|
| Missing SONAME | Consumers record bare filename; library versioning breaks | [case05](https://github.com/napetrov/abicheck/tree/main/examples/case05_soname) |
| Visibility leak (no `-fvisibility=hidden`) | Internal symbols become public ABI surface you must maintain forever | [case06](https://github.com/napetrov/abicheck/tree/main/examples/case06_visibility) (fixing later = BREAKING) |
| Executable stack (`GNU_STACK RWX`) | Disables NX protection process-wide; trivial exploit target | [case49](https://github.com/napetrov/abicheck/tree/main/examples/case49_executable_stack) |
| RPATH leak (hardcoded build path) | Library only works on the build machine; deployment fails everywhere else | [case52](https://github.com/napetrov/abicheck/tree/main/examples/case52_rpath_leak) |
| Namespace pollution (generic names) | Unprefixed symbols like `init()` collide across libraries | [case53](https://github.com/napetrov/abicheck/tree/main/examples/case53_namespace_pollution) (fixing later = BREAKING) |

---

## Prevention Patterns

| Pattern | Protects Against | How |
|---------|-----------------|-----|
| `-fvisibility=hidden` + explicit exports | Visibility leaks, accidental ABI surface | Only annotated symbols enter `.dynsym` |
| Pimpl / opaque handles | Struct layout breaks | Callers see `T*` only; fields are private |
| Symbol versioning (version script) | Symbol removal, version node breaks | Map file controls what's exported per version |
| SONAME with major-version bump | All breaking changes | `libfoo.so.1` to `libfoo.so.2` on ABI break |
| Reserved fields in public structs | Future field additions | `void *_reserved[4]` absorbs growth without size change |
| CI ABI check with abicheck | All of the above | Catches regressions before merge (see below) |

---

## CI One-Liner

```bash
abicheck compare libfoo.so.old libfoo.so.new \
  --old-header include/old/foo.h \
  --new-header include/new/foo.h \
  --policy strict_abi
```

Exits non-zero on any 🔴 BREAKING or 🟠 API_BREAK finding. Add `--suppress suppressions.yaml` to allowlist known acceptable changes. See [CLI Usage](../user-guide/cli-usage.md) and [Policies](../user-guide/policies.md) for options.

---

## Verdict Quick Reference

| Icon | Verdict | Meaning |
|------|---------|---------|
| 🔴 | BREAKING | Binary incompatible -- consumers crash or misbehave |
| 🟠 | API_BREAK | Source incompatible -- recompilation fails, binary works |
| 🟡 | COMPATIBLE_WITH_RISK | Binary works, deployment risk present |
| 🟡 | COMPATIBLE (quality) | Binary works, bad practice detected |
| 🟢 | COMPATIBLE (addition) | New API surface, fully backward-compatible |
| ✅ | NO_CHANGE | Identical ABI |

Full verdict semantics: [Verdicts](verdicts.md) | All example cases: [Scenario Catalog](https://github.com/napetrov/abicheck/tree/main/examples)
