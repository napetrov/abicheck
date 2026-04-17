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

<!-- filled by agent 3 -->

## Part 4: ELF and Linker-Level Concerns

<!-- filled by agent 4 -->

## Part 5: Subtle and Transitive Breaks

The breaks covered in this part are the ones that survive code review. The
exported symbol table is byte-identical, every function keeps its signature, and
`nm --dynamic` reports no diff between `libfoo.so.1` and its replacement — yet
consumers corrupt memory on the first call. What these cases share is a
*transitive* dependency: an ABI contract implied by a type the library doesn't
itself define but publishes through a header, a padding field, or a nested
member. Static analyzers that look only at the shipped `.so` miss them;
DWARF-aware tools catch most but require debug info to travel with the binary.

### Dependency Leaks

When a public header includes a third-party type — `std::string`, `boost::any`,
`tbb::task_arena`, `grpc::Status` — the library silently inherits that type's
ABI contract. Upgrade the third-party library and every consumer's compiled
size, field offsets, and vtable assumptions become wrong, even though the
wrapper library's own source never changed.
[Case 18](../../examples/case18_dependency_leak/README.md) demonstrates this
with a `ThirdPartyHandle` that grows from 4 to 8 bytes: `libfoo`'s exported
symbols are identical, `nm` and naive `abidiff` see no difference, but a caller
built against v1 headers allocates a 4-byte struct that the v2 library reads
8 bytes from. libstdc++'s dual-ABI split (`std::string` after GCC 5) and the
TBB 2021.3 `task_arena` re-layout both propagated through exactly this
mechanism, fracturing every consumer that had leaked the type into its public
API. abicheck flags this only when DWARF for the third-party type is present
in the shipped `.so`; stripped distributions hide the hazard entirely, which
is why the fix is structural — pimpl or opaque handles — not tooling.

### Anonymous Structs

C and C++ permit unnamed nested structs and unions inside a public type. The
containing type's size and alignment depend entirely on the unnamed member's
contents, but the anonymous member has no stable name to refer to in a diff,
and in C++ it changes the mangled layout without touching any source-visible
identifier.
[Case 36](../../examples/case36_anon_struct/README.md) shows a
`struct Variant { int tag; union { int i; float f; }; }` where replacing
`float f` with `double d` inflates the union from 4 to 8 bytes and shifts the
whole struct's size from 8 to 16, moving `i` from offset 4 to offset 8 due to
8-byte alignment. A caller allocating `sizeof(Variant) == 8` on the stack then
calls into a v2 library that reads `i` at offset 8, four bytes past the
allocation, and lands in uninitialized memory. The source diff is one line
inside an anonymous scope; the ABI diff is total. abicheck traces the layout
through DWARF's anonymous-member rules and reports it as `TYPE_SIZE_CHANGED`
with the exact member offset delta.

### Type Kind Changes

Swapping `struct` for `union`, `enum` for plain `int`, or `class` for `struct`
at the same name — even when the size happens to match — is always an ABI
break, because the *semantics* of member storage differ.
[Case 55](../../examples/case55_type_kind_changed/README.md) changes `Data`
from a struct with sequential fields `x, y` (size 8) to a union where `x` and
`y` overlap at offset 0 (size 4): `sizeof` shrinks, `y`'s offset moves, and
writing one member now clobbers the other. Even a same-size swap — for
example, `enum E : int` to plain `int` in a C++ API — breaks overload
resolution and name mangling (`E` and `int` mangle differently), so function
symbols vanish from the new `.so`. abicheck reads DWARF's
`DW_TAG_structure_type` vs `DW_TAG_union_type` vs `DW_TAG_enumeration_type`
and classifies any transition as `TYPE_KIND_CHANGED` / BREAKING regardless of
byte-for-byte size equality, because a consumer's code generation assumes the
kind, not just the footprint.

### Reserved Field Misuse

Reserving padding fields for future growth — `int __reserved1`,
`char _pad[16]` — is the standard way to extend a struct without bumping
SONAME, but it only works if *no shipped binary ever touched the reserved
bytes*. The moment a consumer writes to reserved storage (deliberately, via a
cast, or accidentally, via `memset(&s, 0xFF, sizeof(s))` followed by
field-wise init), repurposing those bytes becomes a silent data corruption.
[Case 54](../../examples/case54_used_reserved_field/README.md) shows the
*correct* pattern: v1 ships `__reserved1` and `__reserved2` at defined
offsets; v2 renames them to `priority` and `max_retries` with the same types
and offsets, and abicheck's `_diff_reserved_fields` detector recognizes the
naming convention (`__reserved`, `_reserved`, `__pad`, `_unused`) and
classifies the transition as COMPATIBLE. The hazard is that there is no way
for the library author to *verify* that no consumer ever wrote to the
reserved slot; the safety of the pattern rests on a documented contract that
users zero-initialize and ignore the field. Linux's `struct stat`, glibc's
`pthread_attr_t`, and Wayland's protocol structs all rely on exactly this
contract.

### Leaf Structs Through Pointers

Pointer indirection is the single strongest ABI firewall available in C: a
caller that handles only `T*` is agnostic to `sizeof(T)`, to `T`'s field
offsets, and to the kind-tag of `T`.
[Case 48](../../examples/case48_leaf_struct_through_pointer/README.md)
contrasts this with the failing case — a `Container` that *embeds* `Leaf` by
value. When `Leaf` grows from 4 to 8 bytes, `Container::flags` shifts from
offset 8 to offset 16; the public API still takes only `Container*`, but the
size change propagates through embedding, and a v1-compiled caller reads
`flags` at the wrong offset. The fix is to replace the embedded `Leaf` with
`Leaf*` (pointer to incomplete type declared via `struct Leaf;`): the caller's
compilation now depends only on pointer size, which is stable per ABI, and
the library alone controls allocation and layout. This is the mechanism
behind every opaque-handle C API (`FILE*`, `sqlite3*`, `git_repository*`) —
the only type that crosses the ABI boundary is a pointer, so layout evolution
is private to the library.

> **Best practice**
>
> - **Opaque wrappers around third-party types.** Never forward-publish
>   `std::string`, `boost::any`, `tbb::task_arena`, or any vendored-dependency
>   type in your headers; wrap it in a type you own and control.
> - **Stable DTOs at the API boundary.** Define plain structs with explicit
>   layout for every value that crosses the ABI, and treat those DTOs as a
>   versioned schema separate from the library's internal types.
> - **Build-time abicheck in CI.** Run `abicheck compare` against the last
>   released `.so` on every PR; flag anything above `COMPATIBLE_WITH_RISK` as
>   a release blocker.
> - **Zero reserved fields before public release**, or commit in documentation
>   to never activating them. Reserved padding that is never used is free;
>   reserved padding whose safety you can't audit is a future BREAKING
>   verdict.
> - **Pointer-to-incomplete-type for anything you might evolve.** If you
>   can't guarantee a struct's layout for the lifetime of a SONAME, don't
>   expose the definition — expose a forward-declared tag and a
>   constructor/destructor pair.
