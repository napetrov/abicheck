# Change Kind Reference

This page lists all `ChangeKind` values detected by abicheck, their default verdict,
and what they mean. Use this reference to understand what each detected change implies
for binary ABI compatibility, source API compatibility, or neither.

**Verdict overview:**

| Verdict | Meaning |
|---------|---------|
| `BREAKING` | Binary ABI break — existing compiled binaries may crash, fail to load, or produce incorrect results. |
| `API_BREAK` | Source API break — existing source code will fail to compile, but compiled binaries are still compatible. |
| `COMPATIBLE` | Compatible change — additive or informational; no impact on existing binaries or source. |

---

## Binary ABI Breaks (`BREAKING`)

These changes are immediately incompatible with existing compiled binaries.

### Function Changes

| Kind | Description |
|------|-------------|
| `func_removed` | Public function removed from the exported symbol table. Callers crash at load time with an undefined symbol error. |
| `func_return_changed` | Function return type changed. Callers reading the return value will interpret the wrong bytes — silent data corruption or crashes. |
| `func_params_changed` | Function parameter types or count changed. The calling convention breaks: arguments are placed in wrong registers/stack slots. |
| `func_virtual_added` | A non-virtual method became virtual. Changes the vtable layout: any class with this as a base will have a different vtable offset for all methods after this one. |
| `func_virtual_removed` | A virtual method is no longer virtual. Vtable layout collapses — all vtable offsets shift for derived classes. |
| `func_static_changed` | A method changed from static to non-static or vice versa. The calling convention changes (implicit `this` pointer added/removed). |
| `func_cv_changed` | `const` or `volatile` qualifier on `this` changed. This changes the mangled name and the overload set — existing binaries resolve the wrong symbol. |
| `func_visibility_changed` | Function visibility changed from default to hidden. The symbol disappears from the dynamic symbol table — callers get undefined symbol at link or load time. |
| `func_pure_virtual_added` | A virtual function became pure virtual. Any concrete class that does not implement it is now abstract — instantiation fails at link time. |
| `func_virtual_became_pure` | A virtual method that had a default implementation is now pure. Derived classes that relied on the base implementation now fail to link. |
| `func_deleted` | A function was marked `= delete`. Previously callable code now gets a link-time error (callers compiled against old header had no error). |
| `func_noexcept_added` | `noexcept` specifier added to a function. Under C++17 (P0012R1), `noexcept` is part of the function type — this changes the mangled name. |
| `func_noexcept_removed` | `noexcept` specifier removed. Widens the exception specification — callers compiled against the old declaration may violate their exception contracts. |

### Variable Changes

| Kind | Description |
|------|-------------|
| `var_removed` | Exported global variable removed. Callers crash at load time with an undefined symbol error. |
| `var_type_changed` | Global variable type changed. Callers reading the variable will interpret memory incorrectly — wrong size, alignment, or layout. |
| `var_became_const` | A non-const variable became const. The linker may move it to `.rodata` — existing binaries writing to it receive `SIGSEGV`. |
| `var_lost_const` | A const variable lost its `const` qualifier. Callers may have inlined the value at compile time (ODR violation) — stale values or crashes. |

### Type / Struct Changes

| Kind | Description |
|------|-------------|
| `type_size_changed` | struct/class total size changed. Callers allocating instances on the stack or inside other structs will use the wrong allocation size. |
| `type_alignment_changed` | Alignment requirement of a struct/class changed. Critical on ARM/RISC-V where misaligned access causes bus errors or data corruption. |
| `type_field_removed` | A field was removed from a struct/class. All field offsets after the removal point shift — binary layout of any consumer is wrong. |
| `type_field_added` | A field was added to a polymorphic or non-standard-layout struct/class. Can change size and offsets for all following fields. |
| `type_field_offset_changed` | A struct/class field moved to a different byte offset. Any caller accessing that field reads the wrong bytes. |
| `type_field_type_changed` | A struct/class field changed its type (different size or representation). Callers reading or writing the field get wrong values. |
| `type_base_changed` | Base class list changed (class added, removed, or reordered). This-pointer offsets for all bases that follow the change are invalidated. |
| `type_vtable_changed` | Virtual table layout changed. All virtual dispatch through this class or its derivatives will call wrong functions. |
| `type_removed` | A type used in the public API was completely removed. Any caller referencing the type gets a link-time undefined symbol error. |
| `type_became_opaque` | A previously complete type became a forward declaration only. Callers that used the full definition (stack allocation, field access) now fail to compile or link. |
| `type_kind_changed` | The kind of a type changed (e.g., `struct` → `union` or `union` → `class`). The entire memory layout model changes — catastrophic ABI break. |

### Base Class Changes

| Kind | Description |
|------|-------------|
| `base_class_position_changed` | An inherited base class was reordered in the inheritance list. The this-pointer offset for the shifted base changes — virtual dispatch and casts break. |
| `base_class_virtual_changed` | A base class became virtual or stopped being virtual. This alters the vptr placement and diamond-inheritance layout — complete vtable/layout break. |

### Enum Changes

| Kind | Description |
|------|-------------|
| `enum_member_removed` | An enumerator value was removed. Switch statements and comparisons that relied on its existence break silently or crash. |
| `enum_member_value_changed` | An enumerator's numeric value changed. Any binary that serialized, compared, or switched on the old value will behave incorrectly. |
| `enum_last_member_value_changed` | The last (often sentinel) enumerator value changed. Loop bounds, array sizes, and sentinel checks using this value are now wrong. |
| `enum_underlying_size_changed` | The underlying integer type of an enum changed size (e.g., `int` → `long`). Struct layout and function parameter sizes change — full ABI break. |

### Typedef Changes

| Kind | Description |
|------|-------------|
| `typedef_removed` | A public typedef was removed. Any consumer using the typedef gets a compile error or link failure depending on the usage. |
| `typedef_base_changed` | The underlying type of a typedef changed. Callers that assumed the original underlying type get incorrect behavior. |

### Union Changes

| Kind | Description |
|------|-------------|
| `union_field_removed` | A field was removed from a union. Code reading the union through the removed member name fails to compile or reads wrong bytes. |
| `union_field_type_changed` | A union field changed its type. The size interpretation of the union changes — binary consumers reading the field get wrong values. |

### Bitfield Changes

| Kind | Description |
|------|-------------|
| `field_bitfield_changed` | A bitfield's width or position changed. Callers accessing packed bitfields read the wrong bits — silent data corruption. |

### DWARF / Struct Layout (Sprint 3–4)

| Kind | Description |
|------|-------------|
| `struct_size_changed` | `sizeof(T)` changed as reported by DWARF. Confirms a binary ABI break for stack/heap allocations. |
| `struct_field_offset_changed` | A struct field's byte offset changed according to DWARF. Callers accessing that field read wrong memory. |
| `struct_field_removed` | A struct field was removed according to DWARF. All following field offsets shift. |
| `struct_field_type_changed` | A struct field changed its type according to DWARF. Layout and semantics change for that field. |
| `struct_alignment_changed` | `alignof(T)` changed according to DWARF. Critical for SIMD types and cross-platform code. |
| `calling_convention_changed` | The calling convention for a function changed (from DWARF `DW_AT_calling_convention`). Arguments are passed via different registers or stack layout. |
| `struct_packing_changed` | `__attribute__((packed))` was added or removed. Changes every field offset and the total size — complete struct layout break. |
| `type_visibility_changed` | RTTI typeinfo or vtable visibility changed. Cross-DSO `dynamic_cast` and exception matching can silently fail. |

### Pointer / Parameter Level Changes

| Kind | Description |
|------|-------------|
| `param_pointer_level_changed` | A parameter changed its pointer indirection level (e.g., `T*` → `T**`). The ABI representation size changes — callers pass the wrong data. |
| `return_pointer_level_changed` | Return type pointer indirection level changed (e.g., `T*` → `T**`). Callers dereference the return value incorrectly. |

### Anonymous Struct/Union

| Kind | Description |
|------|-------------|
| `anon_field_changed` | An anonymous struct or union member changed. Offset arithmetic for all sibling fields may be affected. |

### ELF Symbol Versioning

| Kind | Description |
|------|-------------|
| `symbol_version_defined_removed` | A symbol version definition (`GLIBC_2.5`, etc.) was removed from the library. Binaries linked against that version tag cannot find the symbol. |
| `symbol_version_required_added` | A new required symbol version appeared in the library (e.g., new `GLIBC_X.Y` dependency). The library now fails to load on runtimes that lack that version. |

### ELF Dynamic Section

| Kind | Description |
|------|-------------|
| `soname_changed` | The library SONAME changed. Any binary linked against the old SONAME will fail to load at runtime — the dynamic linker cannot find the library. |
| `symbol_type_changed` | Symbol type changed in the ELF `.dynsym` (e.g., `STT_FUNC` → `STT_OBJECT`). The dynamic linker may handle it incorrectly — undefined behavior at runtime. |
| `symbol_size_changed` | Symbol size (`st_size`) changed in ELF `.dynsym`. In ELF-only analysis mode, this is the primary signal for variable or vtable layout changes. |

---

## Source API Breaks (`API_BREAK`)

These changes break source-level compilation but do not affect already-compiled binaries.

### Naming and Renaming

| Kind | Description |
|------|-------------|
| `enum_member_renamed` | An enumerator was renamed (same value, different name). Source code referencing the old name fails to compile. |
| `field_renamed` | A struct/class field was renamed (same offset and type). Source code accessing the old field name fails to compile. |
| `param_renamed` | A function parameter was renamed. Source code using designated initializers or named argument extensions breaks. |

### Default Argument Changes

| Kind | Description |
|------|-------------|
| `param_default_value_removed` | A default argument was removed from a function parameter. Call sites that omitted that argument now fail to compile. |

### Access Level Changes

| Kind | Description |
|------|-------------|
| `method_access_changed` | A method's access level narrowed (e.g., `public` → `protected` or `private`). Source code calling the method on the old access level fails to compile. |
| `field_access_changed` | A field's access level narrowed (e.g., `public` → `private`). Source code directly accessing the field fails to compile. |
| `var_access_changed` | A global/static variable's access level narrowed. Source code that directly accessed the variable fails to compile. |

### Source-Level Kind Change

| Kind | Description |
|------|-------------|
| `source_level_kind_changed` | A type changed between `struct` and `class`. In C++ these have identical binary layout, but source code using the keyword explicitly may get compilation warnings or errors in strict contexts. |

### Overload Changes

| Kind | Description |
|------|-------------|
| `removed_const_overload` | A `const` method overload was removed. Source code calling the method on a `const` object now fails to compile or selects a different overload silently. |

### Preprocessor Constants

| Kind | Description |
|------|-------------|
| `constant_changed` | A `#define` constant's value changed. Source code that used the constant in a way that depended on its exact value gets different behavior at compile time. |
| `constant_removed` | A `#define` constant was removed entirely. Source code referencing it fails to compile. |

---

## Compatible Changes (`COMPATIBLE`)

These changes are safe: they add new capabilities or carry diagnostic information without affecting existing consumers.

### New Symbols

| Kind | Description |
|------|-------------|
| `func_added` | A new public function was exported. Existing binaries are unaffected; new callers can use it. |
| `var_added` | A new public global variable was exported. Existing binaries are unaffected. |
| `type_added` | A new type was added to the public API. Additive — existing consumers are unchanged. |
| `type_field_added_compatible` | A field was appended to a standard-layout, non-polymorphic struct. Size increases but no existing field offsets shift. Compatible only for types meeting the standard-layout criteria. |
| `func_removed_elf_only` | An ELF-only symbol (no public header declaration) was removed. This is a visibility cleanup — not a public ABI break since headers never exposed the symbol. |

### Enum Additions

| Kind | Description |
|------|-------------|
| `enum_member_added` | A new enumerator value was added. Existing compiled code that does not switch on all values is unaffected. Value shifts for other members are caught separately by `enum_member_value_changed`. |

### Union Additions

| Kind | Description |
|------|-------------|
| `union_field_added` | A new field was added to a union. All union fields start at offset 0 — no existing field offset shifts. Size increase (if any) is caught by `type_size_changed`. |

### noexcept Changes

| Kind | Description |
|------|-------------|
| `func_noexcept_added` | `noexcept` added to a function. The Itanium ABI mangling does not change in practice; existing compiled binaries resolve the same symbol. A source-level concern for function-pointer typing only. |
| `func_noexcept_removed` | `noexcept` removed from a function. Existing binaries continue to resolve the symbol. A source-level exception-specification concern only. |

### ELF Dynamic Section

| Kind | Description |
|------|-------------|
| `soname_missing` | The old library had no SONAME — a packaging defect. The new library adds a SONAME, which is an improvement. |
| `visibility_leak` | The library exports internal symbols without `-fvisibility=hidden`. This is a diagnostic warning, not a break — no existing consumer relies on those symbols being absent. |
| `needed_added` | A new `DT_NEEDED` dependency was added. Existing consumers may not have the new dependency on their system — warn, but not a hard break. |
| `needed_removed` | A `DT_NEEDED` dependency was removed. Existing consumers that transitively relied on the removed dep may have unresolved symbols — deployment risk but not a proven break. |
| `rpath_changed` | The library `RPATH` changed. Runtime search path for transitive dependencies changes — a deployment/packaging concern. |
| `runpath_changed` | The library `RUNPATH` changed. Runtime search path changes — deployment concern. |
| `symbol_binding_changed` | Symbol binding changed from `GLOBAL` to `WEAK`. The symbol is still exported and resolvable; interposition semantics change but existing compiled binaries continue to work. |
| `symbol_binding_strengthened` | Symbol binding changed from `WEAK` to `GLOBAL`. Backward-compatible for all consumers. |
| `ifunc_introduced` | A function was changed from a regular function to a `STT_GNU_IFUNC` (GNU indirect function). The PLT/GOT mechanism transparently handles resolution — callers are unaffected. |
| `ifunc_removed` | A `STT_GNU_IFUNC` was changed back to a regular function. Transparent to callers via PLT/GOT. |
| `common_symbol_risk` | A `STT_COMMON` symbol is exported. Common symbols have merge semantics that can cause surprising behavior — a risk warning, not a proven break. |
| `symbol_version_defined_added` | Symbol versioning was introduced to the library (a new version definition added). New binaries link against the versioned symbol; old binaries use the unversioned fallback. |
| `symbol_version_required_removed` | A previously required symbol version dependency was dropped. Reduces the minimum libc/glibc requirement — compatible or an improvement. |

### DWARF Diagnostics

| Kind | Description |
|------|-------------|
| `dwarf_info_missing` | The new binary was stripped of debug info (`-g`). abicheck cannot perform DWARF-based comparison — this is a coverage gap warning, not a proven ABI break. |
| `toolchain_flag_drift` | Toolchain flags drifted between builds (e.g., `-fshort-enums`, `-fpack-struct`). Informational — may indicate a real break that other checks (size, alignment) would catch. |

### Field Qualifier Changes

| Kind | Description |
|------|-------------|
| `field_became_const` | A struct field became `const`. No binary layout change; a source-level annotation. |
| `field_lost_const` | A struct field lost its `const` qualifier. No binary layout change. |
| `field_became_volatile` | A struct field became `volatile`. No binary layout change; changes compiler optimization behavior. |
| `field_lost_volatile` | A struct field lost its `volatile` qualifier. No binary layout change. |
| `field_became_mutable` | A struct field became `mutable`. No binary layout change; source-level annotation change. |
| `field_lost_mutable` | A struct field lost its `mutable` qualifier. No binary layout change. |

### Parameter Changes (Informational)

| Kind | Description |
|------|-------------|
| `param_default_value_changed` | A default argument value changed. Existing compiled call sites are unaffected (the default is encoded at the call site, not in the library). Informational only. |
| `param_restrict_changed` | A `restrict` qualifier was added or removed from a parameter. `restrict` is an optimization hint — no ABI impact. |
| `param_became_va_list` | A fixed parameter was replaced with a `va_list`. Informational — the actual parameter change is caught separately by `func_params_changed`. |
| `param_lost_va_list` | A `va_list` parameter was replaced with a fixed parameter. Informational. |

### Preprocessor Constants

| Kind | Description |
|------|-------------|
| `constant_added` | A new `#define` constant was added. Purely additive — no existing consumer is affected. |

### Global Data

| Kind | Description |
|------|-------------|
| `var_value_changed` | A global variable's initial value changed. Compile-time values inlined by the compiler may differ, but the binary ABI (symbol presence and type) is unchanged. |
| `used_reserved_field` | A previously `__reserved` field was put into use. Since reserved fields are allocated space but semantically undefined, using them is compatible (was unused). |
| `var_access_widened` | A variable's access level widened (e.g., `private` → `public`). Widening is always compatible. |
