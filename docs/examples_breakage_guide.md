# Full guide to ABI/API breakage cases in `examples/`

This page is a practical guide for every case in `examples/case01..case24`:

- what exactly breaks compatibility,
- what risk it creates for downstream users,
- how to prevent or mitigate the break.

> Recommended release workflow: run these cases as a regression suite and record
> in changelog/release notes why each change is considered compatible or breaking.

## Cases: what breaks and how to avoid it

| Case | What breaks dependency compatibility | How to avoid/mitigate |
|---|---|---|
| [`case01_symbol_removal`](../examples/case01_symbol_removal/README.md) | Removing an exported symbol causes `undefined symbol` at load/runtime for old consumers. | Do not remove symbols in a stable major line; keep a shim wrapper; deprecate for at least one release. |
| [`case02_param_type_change`](../examples/case02_param_type_change/README.md) | Changing a parameter type changes call ABI (register/stack usage). | Add a new function with a new signature; keep the old function as a compatibility wrapper. |
| [`case03_compat_addition`](../examples/case03_compat_addition/README.md) | Adding a symbol is usually compatible, but can expand unstable API surface. | Add symbols with explicit versioning policy and compatibility tests. |
| [`case04_no_change`](../examples/case04_no_change/README.md) | Control case with no ABI changes. | Use as CI baseline to detect false positives. |
| [`case05_soname`](../examples/case05_soname/README.md) | Incorrect SONAME policy breaks package/runtime dependency resolution. | Enforce strict SONAME policy: major ABI break => new SONAME. |
| [`case06_visibility`](../examples/case06_visibility/README.md) | Internal symbols leak to exports, creating accidental public contract lock-in. | Use `-fvisibility=hidden` by default + explicit export macros for public API only. |
| [`case07_struct_layout`](../examples/case07_struct_layout/README.md) | Struct layout changes (size/offset/alignment) break old binaries. | Do not mutate public structs in place; use opaque handles/Pimpl; evolve via versioned APIs. |
| [`case08_enum_value_change`](../examples/case08_enum_value_change/README.md) | Enum numeric value changes break protocol/wire format/switch behavior. | Pin explicit enum values; never reuse old numeric IDs; only append new values. |
| [`case09_cpp_vtable`](../examples/case09_cpp_vtable/README.md) | Virtual interface changes alter vtable and break C++ binary compatibility. | Freeze virtual ABI; use interface versioning/adapters for evolution. |
| [`case10_return_type`](../examples/case10_return_type/README.md) | Return type changes alter ABI and value interpretation. | Keep old function; introduce a new versioned function (e.g., `foo_v2`). |
| [`case11_global_var_type`](../examples/case11_global_var_type/README.md) | Global variable type change breaks size/alignment/access expectations. | Avoid public mutable globals; expose state through getter/setter API. |
| [`case12_function_removed`](../examples/case12_function_removed/README.md) | Removing a function is a hard ABI break for existing consumers. | Deprecate first; remove only in major release with SONAME bump and migration notes. |
| [`case13_symbol_versioning`](../examples/case13_symbol_versioning/README.md) | Losing symbol versioning reduces compatibility control across distros/releases. | Maintain map/version scripts and validate them in CI. |
| [`case14_cpp_class_size`](../examples/case14_cpp_class_size/README.md) | Class size/layout changes break object allocation/layout contract. | Use Pimpl for public C++ classes; avoid exposing layout-sensitive fields. |
| [`case15_noexcept_change`](../examples/case15_noexcept_change/README.md) | `noexcept` contract changes can break mixed-build compatibility expectations. | Treat `noexcept` as API contract; change only via new API version. |
| [`case16_inline_to_non_inline`](../examples/case16_inline_to_non_inline/README.md) | inline↔non-inline transitions can change ODR/link behavior across translation units. | Keep stable inlining strategy for public headers; move implementation to `.cpp` where possible. |
| [`case17_template_abi`](../examples/case17_template_abi/README.md) | Template layout/instantiation changes can break cross-module ABI. | Minimize template types in public ABI; use type erasure/opaque wrappers. |
| [`case18_dependency_leak`](../examples/case18_dependency_leak/README.md) | Public API leaks third-party types; dependency upgrade breaks ABI even if your `.so` is unchanged. | Do not expose third-party types directly; introduce stable DTO/opaque handle boundary. |
| [`case19_enum_member_removed`](../examples/case19_enum_member_removed/) | Removing enum members breaks compatibility with compiled code/persisted values. | Keep old values; mark deprecated but preserve them for backward compatibility. |
| [`case20_enum_member_value_changed`](../examples/case20_enum_member_value_changed/) | Reassigning enum numeric values breaks wire format and persisted data. | Treat enum numeric values as immutable; add new constants for new semantics. |
| [`case21_method_became_static`](../examples/case21_method_became_static/) | Method -> static changes signature/call ABI for C++ clients. | Add new static method under new name; keep old method as adapter. |
| [`case22_method_const_changed`](../examples/case22_method_const_changed/) | Changing method `const` qualifier changes mangling/overload set. | Do not change public const contract in place; add overload/new API name. |
| [`case23_pure_virtual_added`](../examples/case23_pure_virtual_added/) | Adding pure virtual method breaks inheritors and vtable compatibility. | Add a new interface version (`IFoo2`) and keep the old one stable. |
| [`case24_union_field_removed`](../examples/case24_union_field_removed/) | Removing union field changes valid data representations and ABI contract. | Keep public unions stable; evolve using versioned replacement type/wrapper. |

## General rules to avoid ABI breakage

1. Treat any public signature/type change as potentially **breaking**.
2. For C++ ABI stability, prefer **Pimpl/opaque handles**.
3. Stabilize exports with visibility policy + symbol versioning + SONAME discipline.
4. Evolve via **versioned APIs**, not in-place edits of old contracts.
5. Keep `examples/` as a release regression suite in CI.
