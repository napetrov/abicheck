# ABI Stability Guide

## Introduction

An **API** (Application Programming Interface) is a *source-level* contract: the set of declarations — function signatures, type definitions, macros, and semantic guarantees — that a consumer's source code compiles against. An **ABI** (Application Binary Interface) is the *binary-level* contract between already-compiled artifacts: the exact byte-level layout of types, symbol names and mangling, calling conventions, register usage, vtable shapes, stack-unwinding metadata, and the relocation rules that the dynamic linker relies on. An API break forces downstream code to be edited; an ABI break does not — but it silently corrupts memory, misroutes calls, or fails to resolve symbols at load time, because the consumer binary was produced under assumptions the new library no longer satisfies.

The cost of an ABI break compounds with the size of the ecosystem depending on the library. When `libfoo.so.1` breaks ABI without bumping its SONAME, a Linux distribution must rebuild — and re-test, re-sign, and re-ship — every reverse-dependency in the archive; Debian and Fedora each track hundreds of such transitions per release. In embedded and firmware contexts, an ABI break shipped in an OTA update can brick devices in the field when a pre-linked application loads a new system library whose struct offsets have shifted. Plugin ecosystems — audio hosts loading VST modules, game engines loading mods, browsers loading NPAPI/PPAPI components, IDEs loading extensions — fracture entirely when the host's ABI changes: third-party binaries that shipped years earlier fault on first call, and the plugin author may no longer exist to rebuild them.

abicheck classifies every comparison into one of five verdicts — `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK`, `API_BREAK`, and `BREAKING` — mapped to CI exit codes so that release gates can distinguish a harmless symbol addition from a silent memory-corruption hazard. The five tiers and their exit-code semantics are documented in detail in [./verdicts.md](./verdicts.md). This guide catalogs the concrete mechanisms by which ABI breaks occur; for a condensed checklist consult [./abi-cheat-sheet.md](./abi-cheat-sheet.md), and for a taxonomy of detected breaks see [./abi-breaks-explained.md](./abi-breaks-explained.md).

## Part 1: Symbol Contract Breaks

The dynamic linker (`ld.so` on Linux, `dyld` on macOS, the PE loader on Windows) resolves every external reference in an executable by name at load time or at first call. A symbol that existed at link time but is missing at load time is a hard error — no fallback, no default, just `symbol lookup error` and process termination. The four classes of break below each violate the name-keyed contract in a different way: by erasing the name, by keeping the name but changing what it means, by preserving type size while changing type meaning, or by letting a data symbol drift out from under consumers that baked its layout into their own binary.

### Removing or renaming symbols

When an executable is linked against `libfoo.so.1`, every reference to a library function is recorded as a named relocation in the binary's `.rela.plt` (for functions) or `.rela.dyn` (for data). At load time `ld.so` walks those relocations and performs `dlsym`-equivalent lookups against the library's `.dynsym` table. If the name is absent — whether v2 dropped it entirely (see [case01](https://github.com/napetrov/abicheck/blob/main/examples/case01_symbol_removal/README.md), where `helper` disappears) or only kept a differently-named function alongside the deletion (see [case12](https://github.com/napetrov/abicheck/blob/main/examples/case12_function_removed/README.md), where `fast_add` is removed and `other_func` is added) — the lookup returns `NULL` and the process aborts before `main()` under `RTLD_NOW`, or at the first PLT trampoline under the default lazy binding. A rename is the same mechanism: from the loader's viewpoint, renaming `fast_add` to `fast_add_v2` is a removal of the old name plus an addition of the new one, and every pre-existing binary still resolves against the old name. v1 of case01 exports both entry points:

```c
int compute(int x) { return x * 2; }
int helper(int x)  { return x + 1; }
```

v2 drops `helper`, and every downstream binary that ever called it fails with `./app: symbol lookup error: ./app: undefined symbol: helper` until recompiled against v2 headers. Name identity is the only key `.dynsym` is indexed by — which is why the loader cannot distinguish a removal from a rename, and why neither is safe without a SONAME bump.

### Changing function signatures

Signatures are not part of the symbol name in C — `process` mangles to `process` regardless of whether it takes `(int, int)` or `(double, int)` — so the dynamic linker cheerfully binds v1 callers to v2 implementations whose parameter types disagree. The x86-64 System V ABI passes the first six integer-class arguments in `RDI, RSI, RDX, RCX, R8, R9` and the first eight floating-point arguments in `XMM0..XMM7`, with integer and FP registers assigned from independent queues; anything past those queues spills onto the stack in right-to-left order. When [case02](https://github.com/napetrov/abicheck/blob/main/examples/case02_param_type_change/README.md) widens the first parameter from `int` to `double`, the v1 caller loads an integer into `EDI` while the v2 callee reads an FP value from `XMM0` — two disjoint registers — and `XMM0` holds whatever garbage the caller last left there:

```c
/* v1 */ double process(int a, int b)    { return (double)(a + b); }
/* v2 */ double process(double a, int b) { return a + b; }
```

[case10](https://github.com/napetrov/abicheck/blob/main/examples/case10_return_type/README.md) is the mirror failure on the return path: widening `int` → `long` makes the callee write all 64 bits of `RAX`, but v1 callers read only `EAX`, truncating `3_000_000_000` to `-1_294_967_296`. Struct-passing changes are worse still, because aggregates straddle the register/stack boundary by classification rules that depend on size, alignment, and member types — a single added `int64_t` field can push an entire argument onto the stack.

### Pointer-level changes

Every pointer on a 64-bit target occupies 8 bytes, so `int *` and `int **` look identical in a symbol's size on the wire. They are not identical in semantics. The v1 and v2 implementations of [case33](https://github.com/napetrov/abicheck/blob/main/examples/case33_pointer_level/README.md) make the contrast concrete:

```c
/* v1 */ void process(int *data)  { buf[0] = *data; }
/* v2 */ void process(int **data) { buf[0] = **data; }
```

A v1 caller passes the address of a stack `int`; v2 treats that address as an `int *` and dereferences it again, reading the 32-bit integer value as a 64-bit pointer. The result is almost always an unmapped-page fault, but on unlucky memory layouts the synthesised "pointer" lands inside a valid mapping and the library silently reads or writes the wrong bytes — a data-corruption bug with no crash to trace back to. The same failure occurs on the return path: if `get_buffer()` grows from `int *` to `int **`, v1 callers index through a pointer-to-pointer as if it were a flat buffer and walk off into arbitrary memory.

### Global variable changes

Exported globals are the hardest class to refactor compatibly because the executable bakes in layout facts about the variable at link time. On ELF, a reference to an imported data symbol typically generates a **COPY relocation**: the linker allocates space in the executable's own `.bss` sized to `sizeof(v1_type)`, and at load time `ld.so` memcpy's the library's initial value into that executable-owned slot. Subsequent reads and writes on *both* sides redirect to the executable's copy. If v2 widens the type — as in [case11](https://github.com/napetrov/abicheck/blob/main/examples/case11_global_var_type/README.md), `int lib_version` → `long lib_version` — the executable's 4-byte slot cannot hold the 8-byte value; `ld.so` either warns about a size mismatch or silently truncates, so the app reads `705_032_704` where the library wrote `5_000_000_000`. [case58](https://github.com/napetrov/abicheck/blob/main/examples/case58_var_removed/README.md) removes the global outright: the COPY relocation has no target, and the process fails to start with `undefined symbol: lib_debug_level`. [case39](https://github.com/napetrov/abicheck/blob/main/examples/case39_var_const/README.md) shows the qualifier failure mode in two flavours: when COPY relocation is in play (typical for non-PIE executables on ELF), a mutable-in-v1 global that v2 declares `const` still lives in the app's writable `.bss` copy, so app-side writes succeed but the library's own updates never propagate to that copy — the two sides silently diverge. For PIE binaries that reach the library symbol directly through the GOT, the same change moves the variable into the library's `.rodata` and a write from app code faults with SIGSEGV. Either way the combined demo in case39 also removes `g_legacy_flag`, so the process itself fails to start with an undefined-symbol error before the divergence ever becomes observable.

> **Best practice — keeping the symbol contract intact**
>
> - **Deprecate, don't delete.** Mark outgoing functions `__attribute__((deprecated))` for at least one release, ship an alias (`__attribute__((alias("new_name")))`) spanning old and new names, and only remove on a SONAME bump.
> - **Use versioned symbols.** A linker version script (`GLIBC_2.17 { global: foo; };`) lets you ship `foo@GLIBC_2.17` alongside `foo@@GLIBC_2.34`, so pre-existing binaries keep resolving to the old implementation while new links pick up the new one.
> - **Prefer accessors over exported globals.** `int get_version(void)` is immune to COPY-relocation hazards and lets the library change storage, width, or qualifier without touching consumers.
> - **Freeze signatures; add new entry points.** Model the `ftell` → `ftello` pattern: ship a new symbol for the new type rather than widening the existing one.
> - **Hide layout behind opaque handles.** Publish `typedef struct foo foo_t;` with only `foo_t *` in the public header and force consumers through functions — the library then owns the struct's size and layout outright.

## Part 2: Type Layout Breaks

Every aggregate type published in a header is a byte-level contract: its size, its members' offsets, its alignment, and — for C++ — its vtable shape. Consumer code does not re-read that contract at load time. The compiler bakes it into every caller: `offsetof(s, field)` becomes an immediate displacement in a `mov` instruction, `sizeof(T)` becomes an allocation constant, array indexing multiplies by a stride chosen at compile time. When the library's next release shifts even one offset, every call site compiled against the old layout reads or writes at the wrong address — silently, without a linker error, usually without a crash until adjacent memory is eventually read back.

### Struct/Class Size and Offsets

The most common layout break is appending, inserting, or reordering a struct field. In [case07](https://github.com/napetrov/abicheck/tree/main/examples/case07_struct_layout), `struct Point { int x; int y; }` grows to `{ int x; int y; int z; }`. `sizeof(Point)` goes from 8 to 12, so every caller that allocates `Point` on the stack or inside another struct under-allocates; every caller passing `Point` by value sends 8 bytes while the library reads 12. In [case14](https://github.com/napetrov/abicheck/tree/main/examples/case14_cpp_class_size) the same failure mode strikes C++: a `char data[64]` buffer grows to `char data[128]`, `sizeof(Buffer)` doubles, and v1 callers `new Buffer()` hand the constructor a 64-byte allocation that it promptly zero-fills with 128 bytes, corrupting whatever lives next on the heap. [case43](https://github.com/napetrov/abicheck/tree/main/examples/case43_base_class_member_added) shows the transitive case: adding `int extra_field` to `class Base` shifts `Derived::value` from offset 12 to offset 16, so every subclass member in the ecosystem silently moves. [case40](https://github.com/napetrov/abicheck/tree/main/examples/case40_field_layout) bundles five field-level mutations — type widening, removal, reorder, bitfield resize, append — into a single struct to show that "just one field" changes cascade across the whole layout.

### Alignment and Packing

Alignment is the second axis of layout. [case42](https://github.com/napetrov/abicheck/tree/main/examples/case42_type_alignment_changed) changes only the alignment attribute — fields and sizes stay identical — going from `__attribute__((aligned(8)))` to `__attribute__((aligned(64)))`. v1 callers allocate `CacheBlock` on 8-byte boundaries; v2 code may emit aligned-load instructions (e.g., `vmovdqa`) and fault on misaligned access — the signal delivered varies by architecture and OS (commonly `SIGSEGV` on x86-64 Linux, `SIGBUS` on strict-alignment platforms) — and `malloc` (typically 16-byte aligned) can no longer hand out correctly-aligned storage without `aligned_alloc`. [case56](https://github.com/napetrov/abicheck/tree/main/examples/case56_struct_packing_changed) is the inverse: v1 has natural padding (`char tag` at 0, `int value` at 4, total 12), v2 adds `#pragma pack(1)` and eliminates all padding (`value` at offset 1, total 6). `sizeof` shrinks, every field except `tag` moves, and on strict-alignment architectures (ARM, SPARC) the unaligned `int` access traps. Because `alignas` and `#pragma pack` propagate across translation unit boundaries through the header, a single-line change in one header silently rewrites offsets for every TU that includes it.

### Enum Value Stability

Enumerations look like constants, but they are part of the wire format. In [case08](https://github.com/napetrov/abicheck/tree/main/examples/case08_enum_value_change) `{ RED=0, GREEN=1, BLUE=2 }` becomes `{ RED=0, YELLOW=1, GREEN=2, BLUE=3 }`: inserting `YELLOW` in the middle shifts `GREEN` and `BLUE` by one, so every existing binary that tested `== 1` for green now hits the yellow branch. [case20](https://github.com/napetrov/abicheck/tree/main/examples/case20_enum_member_value_changed) changes `ERROR = 1` to `ERROR = 99` — the same symbolic name, a different integer — which is effectively a protocol rewrite without version negotiation. [case19](https://github.com/napetrov/abicheck/tree/main/examples/case19_enum_member_removed) removes an enumerator: any persisted value, any database row, any network message carrying that integer becomes undefined on read. The safe counterpoint is [case25](https://github.com/napetrov/abicheck/tree/main/examples/case25_enum_member_added): appending `YELLOW = 3` to the end does not perturb existing values and is `COMPATIBLE`. A more insidious failure is [case57](https://github.com/napetrov/abicheck/tree/main/examples/case57_enum_underlying_size_changed), which adds a sentinel `= 0x100000000LL` that forces the compiler to widen the underlying type from `int` to `long`; `sizeof(Color)` jumps from 4 to 8, and every struct embedding `Color` silently grows and relocates its subsequent fields.

### Union Layout

Unions share offset 0 across all members, so adding a new variant does not move existing fields — but the union's size equals the largest member, and that size *does* propagate. [case26](https://github.com/napetrov/abicheck/tree/main/examples/case26_union_field_added) adds `double d` to `union Value { int i; float f; }`: `sizeof` grows from 4 to 8, so every stack allocation, every array stride, every embedding struct shifts. This is `TYPE_SIZE_CHANGED` and classified `BREAKING`. By contrast, [case26b](https://github.com/napetrov/abicheck/tree/main/examples/case26b_union_field_added_compatible) adds `int i` to `union { long l; double d; }` where `max(8, 8, 4) == 8` — the union does not grow, nothing downstream moves, and the verdict is `COMPATIBLE`. The rule is: a new union field is safe if and only if `sizeof(new_member) <= sizeof(old_union)` and `alignof(new_member) <= alignof(old_union)`. [case24](https://github.com/napetrov/abicheck/tree/main/examples/case24_union_field_removed) shows the other direction — removing a variant removes a supported reinterpretation, which is a semantic contract break even when the size is unchanged, because consumers compiled to write `d.f = 3.14f` have no replacement for that access path.

### Bitfields and Flexible Arrays

Bitfields are the most fragile layout primitive because storage-unit allocation is implementation-defined. [case63](https://github.com/napetrov/abicheck/tree/main/examples/case63_bitfield_changed) widens `mode` from 3 bits to 5 bits inside a 32-bit `RegMap`. `sizeof` is unchanged — naive size checks pass — but `channel`, `priority`, and `reserved` all shift two bit positions, so every v1 consumer reads corrupt values with no crash and no diagnostic. This pattern bites hardest in hardware-register maps and protocol headers, exactly the contexts where bitfields are most useful. Flexible array members have the opposite static-size profile but the same failure: [case70](https://github.com/napetrov/abicheck/tree/main/examples/case70_flexible_array_member_changed) changes `float data[]` to `double data[]`. The fixed header of `struct Packet` is unchanged — `sizeof(Packet)` compares equal — but every caller that allocated `sizeof(Packet) + count * sizeof(float)` now holds half the needed memory, and `p->data[i]` indexes with stride 8 instead of 4.

### Pointer Chains and Arrays

Multi-level type changes propagate through indirection. [case45](https://github.com/napetrov/abicheck/tree/main/examples/case45_multi_dim_array_change) changes `float data[4][4]` to `double data[4][4]` inside `struct Matrix`: the inner element type changes, the struct doubles from 72 to 136 bytes, the array stride doubles, and both `matrix_get` and `matrix_set` change return/parameter widths so the caller reads the wrong register. [case46](https://github.com/napetrov/abicheck/tree/main/examples/case46_pointer_chain_type_change) reaches further — a function returning `int **` becomes `long **`, a two-level pointer chain where only the ultimate pointee type changes. Every v1 caller that dereferences the returned chain and writes an `int` writes 4 bytes into what v2 treats as an 8-byte cell, corrupting the adjacent slot. abicheck walks pointer and array types structurally during `FUNC_RETURN_CHANGED` and `PARAM_TYPE_CHANGED` detection precisely because a surface-level "both sides return a pointer" comparison would miss these.

> **Best Practice — Defending Type Layout**
>
> - **Opaque handles.** Expose only `struct foo *` to callers; define the struct in a `.c` file. Callers cannot take `sizeof` or `offsetof`, so layout is free to change. OpenSSL 1.1.0's migration from direct `EVP_MD_CTX` access to `EVP_MD_CTX_new`/`EVP_MD_CTX_free` opaque handles is the canonical real-world precedent — it sealed off decades of accumulated struct-layout churn.
> - **Pimpl idiom (C++).** The public class holds a single `d_ptr` to a private `Impl`; all state lives in `Impl`. `sizeof` of the public class never changes. Qt enforces this as a binary-compatibility rule across every public class in every release, which is why Qt 5.x maintained ABI for years despite internal refactors.
> - **Reserved padding fields.** Include `void *reserved[N]` or `uint64_t _pad[N]` at the end of every public struct. Future releases can repurpose slots without changing `sizeof` or shifting offsets. POSIX `pthread_attr_t` and many kernel UAPI structs use this deliberately.
> - **Freeze the enum underlying type.** In C++ write `enum class Color : int32_t { ... };` explicitly; in C keep all values within `int` range or add an explicit sentinel value such as `INT32_MAX`. Never let a new enumerator silently widen the type (see case57).
> - **Never reorder or insert fields — use append-only evolution.** Reordering a field, inserting one in the middle, or removing one is always breaking. If a new field is required, append it at the end of the struct, and only when no embedded `sizeof(T)` assumption exists (see case26 vs case26b for the union analog).

## Part 3: C++ ABI Specifics

<!-- filled by agent 4 -->

## Part 4: ELF and Linker-Level Concerns

<!-- filled by agent 5 -->

## Part 5: Subtle and Transitive Breaks

<!-- filled by agent 6 -->
