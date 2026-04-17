# ABI Stability Guide

## Introduction

An **API** (Application Programming Interface) is a *source-level* contract: the set of declarations — function signatures, type definitions, macros, and semantic guarantees — that a consumer's source code compiles against. An **ABI** (Application Binary Interface) is the *binary-level* contract between already-compiled artifacts: the exact byte-level layout of types, symbol names and mangling, calling conventions, register usage, vtable shapes, stack-unwinding metadata, and the relocation rules that the dynamic linker relies on. An API break forces downstream code to be edited; an ABI break does not — but it silently corrupts memory, misroutes calls, or fails to resolve symbols at load time, because the consumer binary was produced under assumptions the new library no longer satisfies.

The cost of an ABI break compounds with the size of the ecosystem depending on the library. When `libfoo.so.1` breaks ABI without bumping its SONAME, a Linux distribution must rebuild — and re-test, re-sign, and re-ship — every reverse-dependency in the archive; Debian and Fedora each track hundreds of such transitions per release. In embedded and firmware contexts, an ABI break shipped in an OTA update can brick devices in the field when a pre-linked application loads a new system library whose struct offsets have shifted. Plugin ecosystems — audio hosts loading VST modules, game engines loading mods, browsers loading NPAPI/PPAPI components, IDEs loading extensions — fracture entirely when the host's ABI changes: third-party binaries that shipped years earlier fault on first call, and the plugin author may no longer exist to rebuild them.

abicheck classifies every comparison into one of five verdicts — `NO_CHANGE`, `COMPATIBLE`, `COMPATIBLE_WITH_RISK`, `API_BREAK`, and `BREAKING` — mapped to CI exit codes so that release gates can distinguish a harmless symbol addition from a silent memory-corruption hazard. The five tiers and their exit-code semantics are documented in detail in [./verdicts.md](./verdicts.md). This guide catalogs the concrete mechanisms by which ABI breaks occur; for a condensed checklist consult [./abi-cheat-sheet.md](./abi-cheat-sheet.md), and for prescriptive guidance on library design see [./abi-best-practices.md](./abi-best-practices.md).

## Part 1: Symbol Contract Breaks

The dynamic linker (`ld.so` on Linux, `dyld` on macOS, the PE loader on Windows) resolves every external reference in an executable by name at load time or at first call. A symbol that existed at link time but is missing at load time is a hard error — no fallback, no default, just `symbol lookup error` and process termination. The four classes of break below each violate the name-keyed contract in a different way: by erasing the name, by keeping the name but changing what it means, by preserving type size while changing type meaning, or by letting a data symbol drift out from under consumers that baked its layout into their own binary.

### Removing or renaming symbols

When an executable is linked against `libfoo.so.1`, every reference to a library function is recorded as a named relocation in the binary's `.rela.plt` (for functions) or `.rela.dyn` (for data). At load time `ld.so` walks those relocations and performs `dlsym`-equivalent lookups against the library's `.dynsym` table. If the name is absent — because v2 removed it (see [case01](../../examples/case01_symbol_removal/README.md)) or renamed it (see [case12](../../examples/case12_function_removed/README.md)) — the lookup returns `NULL` and the process aborts before `main()` under `RTLD_NOW`, or at the first PLT trampoline under the default lazy binding. v1 of case01 exports both entry points:

```c
int compute(int x) { return x * 2; }
int helper(int x)  { return x + 1; }
```

v2 drops `helper`, and every downstream binary that ever called it fails with `./app: symbol lookup error: ./app: undefined symbol: helper` until recompiled against v2 headers. Renaming is the same failure with a different cause: `fast_add` → `fast_add_v2` is indistinguishable from a removal plus an addition from the loader's perspective, because name identity is the only key that `.dynsym` is indexed by.

### Changing function signatures

Signatures are not part of the symbol name in C — `process` mangles to `process` regardless of whether it takes `(int, int)` or `(double, int)` — so the dynamic linker cheerfully binds v1 callers to v2 implementations whose parameter types disagree. The x86-64 System V ABI passes the first six integer-class arguments in `RDI, RSI, RDX, RCX, R8, R9` and the first eight floating-point arguments in `XMM0..XMM7`, with integer and FP registers assigned from independent queues; anything past those queues spills onto the stack in right-to-left order. When [case02](../../examples/case02_param_type_change/README.md) widens the first parameter from `int` to `double`, the v1 caller loads an integer into `EDI` while the v2 callee reads an FP value from `XMM0` — two disjoint registers — and `XMM0` holds whatever garbage the caller last left there:

```c
/* v1 */ double process(int a, int b)    { return (double)(a + b); }
/* v2 */ double process(double a, int b) { return a + b; }
```

[case10](../../examples/case10_return_type/README.md) is the mirror failure on the return path: widening `int` → `long` makes the callee write all 64 bits of `RAX`, but v1 callers read only `EAX`, truncating `3_000_000_000` to `-1_294_967_296`. Struct-passing changes are worse still, because aggregates straddle the register/stack boundary by classification rules that depend on size, alignment, and member types — a single added `int64_t` field can push an entire argument onto the stack.

### Pointer level changes

Every pointer on a 64-bit target occupies 8 bytes, so `int *` and `int **` look identical in a symbol's size on the wire. They are not identical in semantics. The v1 and v2 implementations of [case33](../../examples/case33_pointer_level/README.md) make the contrast concrete:

```c
/* v1 */ void process(int *data)  { buf[0] = *data; }
/* v2 */ void process(int **data) { buf[0] = **data; }
```

A v1 caller passes the address of a stack `int`; v2 treats that address as an `int *` and dereferences it again, reading the 32-bit integer value as a 64-bit pointer. The result is almost always an unmapped-page fault, but on unlucky memory layouts the synthesised "pointer" lands inside a valid mapping and the library silently reads or writes the wrong bytes — a data-corruption bug with no crash to trace back to. The same failure occurs on the return path: if `get_buffer()` grows from `int *` to `int **`, v1 callers index through a pointer-to-pointer as if it were a flat buffer and walk off into arbitrary memory.

### Global variable changes

Exported globals are the hardest class to refactor compatibly because the executable bakes in layout facts about the variable at link time. On ELF, a reference to an imported data symbol typically generates a **COPY relocation**: the linker allocates space in the executable's own `.bss` sized to `sizeof(v1_type)`, and at load time `ld.so` memcpy's the library's initial value into that executable-owned slot. Subsequent reads and writes on *both* sides redirect to the executable's copy. If v2 widens the type — as in [case11](../../examples/case11_global_var_type/README.md), `int lib_version` → `long lib_version` — the executable's 4-byte slot cannot hold the 8-byte value; `ld.so` either warns about a size mismatch or silently truncates, so the app reads `705_032_704` where the library wrote `5_000_000_000`. [case58](../../examples/case58_var_removed/README.md) removes the global outright: the COPY relocation has no target, and the process fails to start with `undefined symbol: lib_debug_level`. [case39](../../examples/case39_var_const/README.md) shows the qualifier failure mode — a previously mutable global moved from `.data` into `.rodata` causes a SIGSEGV on the first write from code that compiled cleanly against v1, because the page that backs the executable's copy is now mapped read-only.

> **Best practice — keeping the symbol contract intact**
>
> - **Deprecate, don't delete.** Mark outgoing functions `__attribute__((deprecated))` for at least one release, ship an alias (`__attribute__((alias("new_name")))`) spanning old and new names, and only remove on a SONAME bump.
> - **Use versioned symbols.** A linker version script (`GLIBC_2.17 { global: foo; };`) lets you ship `foo@GLIBC_2.17` alongside `foo@@GLIBC_2.34`, so pre-existing binaries keep resolving to the old implementation while new links pick up the new one.
> - **Prefer accessors over exported globals.** `int get_version(void)` is immune to COPY-relocation hazards and lets the library change storage, width, or qualifier without touching consumers.
> - **Freeze signatures; add new entry points.** Model the `ftell` → `ftello` pattern: ship a new symbol for the new type rather than widening the existing one.
> - **Hide layout behind opaque handles.** Publish `typedef struct foo foo_t;` with only `foo_t *` in the public header and force consumers through functions — the library then owns the struct's size and layout outright.

## Part 2: Type Layout Breaks

<!-- filled by agent 3 -->

## Part 3: C++ ABI Specifics

<!-- filled by agent 4 -->

## Part 4: ELF and Linker-Level Concerns

<!-- filled by agent 5 -->

## Part 5: Subtle and Transitive Breaks

<!-- filled by agent 6 -->
