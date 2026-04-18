# ABI Stability Guide

## Introduction

An **API** (Application Programming Interface) is a *source-level* contract: the set of declarations — function signatures, type definitions, macros, and semantic guarantees — that a consumer's source code compiles against. An **ABI** (Application Binary Interface) is the *binary-level* contract between already-compiled artifacts: the exact byte-level layout of types, symbol names and mangling, calling conventions, register usage, vtable shapes, stack-unwinding metadata, and the relocation rules that the dynamic linker relies on. An API break forces downstream code to be edited; an ABI break does not — but it silently corrupts memory, misroutes calls, or fails to resolve symbols at load time, because the consumer binary was produced under assumptions the new library no longer satisfies.

The cost of an ABI break compounds with the size of the ecosystem depending on the library. When `libfoo.so.1` breaks ABI without bumping its SONAME, a Linux distribution must rebuild — and re-test, re-sign, and re-ship — every reverse-dependency in the archive; Debian and Fedora each track hundreds of such transitions per release. In embedded and firmware contexts, an ABI break shipped in an OTA update can brick devices in the field when a pre-linked application loads a new system library whose struct offsets have shifted. Plugin ecosystems — audio hosts loading VST modules, game engines loading mods, browsers loading NPAPI/PPAPI components, IDEs loading extensions — fracture entirely when the host's ABI changes: third-party binaries that shipped years earlier fault on first call, and the plugin author may no longer exist to rebuild them.

abicheck classifies every comparison into one of five verdicts — `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK`, `API_BREAK`, and `BREAKING` — mapped to CI exit codes so that release gates can distinguish a harmless symbol addition from a silent memory-corruption hazard. The five tiers and their exit-code semantics are documented in detail in [./verdicts.md](./verdicts.md). This guide catalogs the concrete mechanisms by which ABI breaks occur; for a condensed checklist consult [./abi-cheat-sheet.md](./abi-cheat-sheet.md), and for prescriptive guidance on library design see [./abi-best-practices.md](./abi-best-practices.md).

## Part 1: Symbol Contract Breaks

<!-- filled by agent 1 -->

## Part 2: Type Layout Breaks

<!-- filled by agent 2 -->

## Part 3: C++ ABI Specifics

C++ is the language where ABI stability is hardest. Every class with a virtual method carries a hidden pointer to a statically-ordered table of function pointers; every method name is mangled through a grammar that encodes qualifiers, namespaces, template arguments, and parameter types; every struct with a user-defined destructor changes how it is passed between functions. The Itanium C++ ABI — used by GCC and Clang on Linux, macOS, the BSDs, and most embedded targets — is rigid by design: it guarantees cross-compiler interoperability at the cost of making almost any visible change to a class a potential binary break. MSVC on Windows uses a different, equally rigid ABI with the same categories of pitfalls. What follows is a tour of the seven C++ mechanisms most likely to silently corrupt a consumer binary.

### 1. Vtable and Virtual Methods

Every polymorphic class carries a hidden `vptr` as its first word, pointing to a per-class vtable — a static array of function pointers indexed by the order virtual methods are declared. The Itanium C++ ABI fixes this slot ordering as a public part of the class contract: callers compile `widget->resize()` into `(*widget->vptr[1])(widget)` where `1` is baked into the call site. The ordering is determined at the point of declaration, propagates unchanged into every derived class, and cannot be renegotiated after the first binary ships.

Inserting a new virtual method *before* an existing one silently shifts every later slot. [case09](../../examples/case09_cpp_vtable/README.md) demonstrates the canonical form: a new `recolor()` at slot 1 reroutes every call to `resize()` into `recolor()`, producing wrong results without a crash. Making an existing method pure-virtual ([case23](../../examples/case23_pure_virtual_added/README.md)) replaces the slot with `__cxa_pure_virtual`, turning every old call site into an unconditional `abort()`.

Adding the *first* virtual method to a previously non-polymorphic class is the most destructive variant ([case68](../../examples/case68_virtual_method_added/README.md)): a vptr is prepended, every data member shifts by `sizeof(void*)`, and `sizeof` grows — readers of the old layout interpret the new vptr as their first field. [case38](../../examples/case38_virtual_methods/README.md) combines virtual-insertion, pure-virtual promotion, and copy-constructor deletion in a single release to show how the hazards compound. The only safe addition is to *append* new virtual methods after every existing slot, and only when no derived classes exist in consumer binaries that would themselves need to extend the vtable.

### 2. Method Qualifiers

Method qualifiers are load-bearing parts of the Itanium mangled name, not cosmetic source-level annotations. A `const` member function mangles with a `K` marker in the parameter list, a `volatile` one with `V`, and ref-qualified methods (`&`/`&&`) with `R`/`O`. Any edit that adds, removes, or flips one of these markers renames the symbol from the linker's perspective.

Dropping `const` from `Widget::get() const` ([case22](../../examples/case22_method_const_changed/README.md)) changes the symbol from `_ZNK6Widget3getEv` to `_ZN6Widget3getEv` — the leading `K` disappears, the old symbol vanishes from `.dynsym`, and every consumer hits `symbol lookup error` at load time. The failure mode is a clean `dlopen` abort rather than silent corruption, which makes it one of the easier C++ breaks to diagnose in production.

Converting an instance method into a `static` one ([case21](../../examples/case21_method_became_static/README.md)) is subtler: the mangled name is often identical (`_ZN6Widget3barEv` for both forms), so the linker is happy, but the calling convention silently diverges — the v1 caller passes an implicit `this` in `%rdi` that the v2 static callee never reads, and the function returns data computed from register garbage. Adding `const`/`volatile` to struct *fields* ([case30](../../examples/case30_field_qualifiers/README.md)) leaves layout unchanged but reclassifies the surface as a source break, and `volatile` additionally invalidates any cached loads in already-compiled callers. Treat every qualifier edit on a public declaration as equivalent to renaming the symbol.

### 3. Templates and Inline

Inline and template code lives at the boundary where the One Definition Rule meets the link model, and that boundary is where ABI assumptions get baked into *consumer* binaries without the library ever seeing them. An explicitly instantiated `Buffer<int>` in `libfoo.so` produces the mangled symbol `_ZN6BufferIiEC1Em`; adding a `capacity_` field ([case17](../../examples/case17_template_abi/README.md)) keeps the symbol name identical while growing `sizeof(Buffer<int>)` from 16 to 24 bytes. The consumer stack-allocates 16 and the v2 constructor writes 24, corrupting the caller's frame — a classic stack smash with no header-level signal.

Header-only inline definitions embed the *body* into each consumer translation unit, so the implementation that callers execute is frozen when they compile. Changing the inline implementation between releases produces ODR violations that LTO can detect and link-time surprises that LTO cannot; worse, two consumers that pulled in different versions of your header will silently disagree about what your function does.

Moving a function from inline-in-header to outlined-in-`.so` ([case47](../../examples/case47_inline_to_outlined/README.md)) is compatible — old binaries keep their inlined copy, new binaries call the export. The inverse transition ([case59](../../examples/case59_func_became_inline/README.md)) or mixing builds where the header says outlined but the `.so` does not ([case16](../../examples/case16_inline_to_non_inline/README.md)) removes the symbol from `.dynsym` and hard-fails at load. Template instantiations, inline functions, and `constexpr` bodies are part of the ABI even though they never appear in `readelf -Ws`.

### 4. Covariant Returns and Inline Namespaces

An **inline namespace** is transparent to source-level name lookup but is mangled into every symbol declared inside it, making it the canonical Itanium mechanism for generational ABI versioning. [case71](../../examples/case71_inline_namespace_moved/README.md) shows a library moving `encrypt` from `inline namespace v1` to `inline namespace v2`: source code that writes `crypto::encrypt(...)` compiles unchanged against both versions, but the emitted symbol goes from `_ZN6crypto2v17encryptE...` to `_ZN6crypto2v27encryptE...` — a clean break for pre-compiled callers.

This is precisely the device libstdc++ uses for its **dual ABI**. GCC 5 introduced `std::__cxx11::basic_string` alongside the legacy COW `std::string`, gated on the `_GLIBCXX_USE_CXX11_ABI` preprocessor switch; every distribution spent years untangling the resulting symbol-lookup failures as users mixed libraries built with the two flavors. The lesson is that inline namespaces are a *power tool*: wielded deliberately they enable forward evolution, but switching them unintentionally renames every symbol you export.

Covariant return types interact with vtable layout directly. A derived `Circle::clone()` returning `Circle*` generates a thunk that adjusts `this` before delegating; inserting a new intermediate base class ([case72](../../examples/case72_covariant_return_changed/README.md)) shifts sub-object offsets, changes the covariant's return type, and invalidates every hardcoded vtable slot in consumer binaries. Used deliberately, inline namespaces let you ship breaking changes under a new mangled surface while keeping the old one exported for compatibility; used accidentally, they are an invisible renaming of every function you declare.

### 5. noexcept

[case15](../../examples/case15_noexcept_change/README.md) is classified `COMPATIBLE_WITH_RISK`, not `BREAKING`, and the reasoning is worth internalizing. Before C++17, `noexcept` was not part of the function type, so the Itanium mangler ignored it: `void reset() noexcept` and `void reset()` both mangle to `_ZN6Buffer5resetEv` and resolve to the same `.dynsym` entry. Removing `noexcept` therefore *does not* break linkage — hence not `BREAKING`.

What it does break is the caller's unwinding assumption. The v1 compiler saw `noexcept` and omitted exception landing pads, cleanup frames, and `.eh_frame` entries in the call site; if the v2 implementation now throws, the exception propagates into a frame with no unwinding metadata and `std::terminate()` fires unconditionally. Every destructor that was supposed to run during stack unwinding is skipped, every `catch` block that would have handled the exception is bypassed, and the process dies.

abicheck also flags the associated GLIBCXX version bump that appears when `throw` is introduced (`SYMBOL_VERSION_REQUIRED_ADDED`), which is a deployment-risk signal rather than a linkage failure. The `_WITH_RISK` tier exists for exactly this shape of change: binary-linkable, source-recompilable, but semantically unsafe for binaries built under the stricter old contract. C++17 promoted `noexcept` to part of the function type, but under the Itanium C++ ABI that only changes mangling in contexts where the full *function-type* is encoded — function pointers, references to functions, and templates parameterized by function type — not in the `<bare-function-type>` used for ordinary member and free-function symbols. So toggling `noexcept` on a plain declaration remains `_WITH_RISK` for those direct symbols, but the same change can escalate to `BREAKING` for callers that pass the function through a pointer or template where the `E` tag on the function-type encoding now participates in the mangled name.

### 6. Trivial to Non-Trivial

The System V AMD64 calling convention — and its equivalents on other Itanium-ABI platforms — passes **trivially-copyable** aggregates directly in registers (`%xmm0`/`%xmm1` for a pair of doubles, `%rdi`/`%rsi` for two pointers), but passes **non-trivially-copyable** ones by invisible reference: the caller materializes the object on the stack and hands the callee a pointer. Whether a class is trivially copyable is determined by whether it has user-provided copy/move/destructor special members — a *single line of code* can flip the register/memory decision.

[case69](../../examples/case69_trivial_to_nontrivial/README.md) shows `struct Point { double x, y; }` gaining an empty user-defined `~Point() {}`: the layout is unchanged, `sizeof` is unchanged, the mangled symbol is unchanged, and the dynamic linker resolves the call perfectly. But the v1 caller passes `x`, `y` in `%xmm0`, `%xmm1` while the v2 callee reads `%rdi`, `%rsi` as pointers and dereferences them — segfault or silent garbage with no diagnostic from the toolchain.

No header-diff tool that looks only at declarations will catch this; abicheck reports it as `value_abi_trait_changed` by inspecting the DWARF trivially-copyable flag. Any class you expect callers to pass by value across a library boundary must have its trivially-copyable status pinned from version 1. If cleanup might ever be needed, commit from day one to a *user-provided* destructor — either an empty body (`~T() {}`) or an out-of-line defaulted definition (`~T();` in the header, `T::~T() = default;` in the `.cpp`). An in-class `~T() = default;` on the first declaration is user-declared but *not* user-provided, so it does not make the type non-trivial and does not pin the calling convention.

### 7. Base Class Position and Layout

Multiple inheritance places each base sub-object at a specific offset inside the most-derived object, and those offsets are compiled into every upcast and virtual call at the call site. [case60](../../examples/case60_base_class_position_changed/README.md) shows the textbook case: swapping `Widget : Drawable, Clickable` to `Widget : Clickable, Drawable` leaves the type name and all method signatures identical, yet `static_cast<Drawable*>(widget)` now produces a pointer into the `Clickable` sub-object because the compiler applied v1's zero offset to a v2 layout that moved `Drawable` further down.

[case37](../../examples/case37_base_class/README.md) generalizes this with three independent hazards on the same class. Reordering bases changes `this`-pointer adjustments and reshuffles which vptr sits at offset 0. Converting non-virtual to `virtual` inheritance restructures the entire object: the virtual base moves to the end of the most-derived layout and a vbase-offset table is inserted to resolve it at runtime. Appending a new base class grows `sizeof` and shifts every data-member offset, just as adding a first virtual method does.

All three variants are reported as `BASE_CLASS_POSITION_CHANGED` or `type_base_changed` when DWARF or header information is available; ELF symbol tables alone cannot see them, which is why C++ ABI checking requires either debug info or headers. Base-class composition is, along with vtable ordering, one of the two C++ design decisions you cannot revisit after publishing a library — prefer composition and Pimpl for anything you expect to evolve.

> **Best Practice — Designing C++ libraries for ABI stability**
>
> - **Interface versioning via pure-virtual interface + factory.** Expose a pure-virtual class (no data members, no inline methods) and a C-linkage factory function `create_foo()`. Consumers hold only the abstract pointer, so you can evolve the implementation class freely without touching any consumer vtable layout.
> - **Non-Virtual Interface (NVI) pattern.** Make your public methods *non-virtual* wrappers that call a small, stable set of `virtual` hooks. You can add new public methods (non-virtual additions are ABI-compatible) without appending vtable slots, and you can change the hook set only when you intend an ABI bump.
> - **ABI firewall via opaque pointers (Pimpl).** Put every data member into an `Impl` struct whose definition lives only in the `.cpp`; the public class holds a single `std::unique_ptr<Impl>`. `sizeof(Widget)` never changes, field offsets are invisible, and you can add, remove, or reorder internal state without ABI consequences.
> - **Inline namespaces for generational ABI.** Wrap every public declaration in `inline namespace abi_v1 { ... }`. When you need a breaking change, ship `abi_v2` alongside `abi_v1` and keep the old symbols exported; consumers migrate on their own schedule, mirroring libstdc++ `__cxx11`.
> - **`-fvisibility=hidden` with explicit export macros.** Compile with hidden default visibility and annotate exported declarations with a `FOO_API` macro (expanding to `__attribute__((visibility("default")))` on ELF and `__declspec(dllexport)` on PE). This shrinks the exported surface to exactly what you intend to stabilize, eliminating accidental ABI commitments on internal helpers, inline template bodies, and private vtables.

## Part 4: ELF and Linker-Level Concerns

<!-- filled by agent 4 -->

## Part 5: Subtle and Transitive Breaks

<!-- filled by agent 5 -->
