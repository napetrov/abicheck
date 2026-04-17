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

<!-- filled by agent 3 -->

## Part 3: C++ ABI Specifics

<!-- filled by agent 4 -->

## Part 4: ELF and Linker-Level Concerns

A second contract sits between the source-level ABI and the running
process: the one enforced by the dynamic linker. SONAME, visibility bits,
version nodes, calling-convention attributes, and the TLS access model are
all recorded in the `.so` and consulted at load time.

### SONAME and Library Identity

The SONAME is how `ld.so` answers "is this the library you asked for?". It
lives in the `DT_SONAME` entry of `.dynamic` and is set via
`-Wl,-soname,libfoo.so.MAJOR` at link time. When an app links against
`libfoo.so`, the linker copies the SONAME — not the filename — into
`DT_NEEDED`, and at runtime `ld.so` searches for a file (usually an
`ldconfig`-managed symlink) matching that string.

[Case 05](../../examples/case05_soname/README.md) covers a library built
without `-Wl,-soname` at all: `DT_NEEDED` points at the bare `libfoo.so`,
which `ldconfig` cannot manage, so shipping `libfoo.so.1` later breaks
every consumer. [Case 50](../../examples/case50_soname_inconsistent/README.md)
is the subtler bug where a 1.x release is tagged `libfoo.so.0`: packaging
generates dependencies on the wrong major, and the cutover forces a
distribution-wide rebuild. Rule: SONAME major equals ABI epoch, and it
never silently changes.

### Symbol Visibility

Every `.dynsym` entry has an `st_other` visibility byte: `STV_DEFAULT`
(public, interposable), `STV_HIDDEN`, `STV_PROTECTED` (exported but not
interposable), or `STV_INTERNAL`. Without `-fvisibility=hidden`, every
non-`static` function defaults to `STV_DEFAULT`, dragging the entire
translation unit into the public ABI.
[Case 06](../../examples/case06_visibility/README.md) is the accidental
leak: `internal_helper` was never intended as public API, but lacking
`static` consumers can resolve it — the later "cleanup" that hides it
breaks them. [Case 53](../../examples/case53_namespace_pollution/README.md)
is the related design error: exporting unprefixed names like `init` that
collide in the process's flat symbol namespace.
[Case 51](../../examples/case51_protected_visibility/README.md) rounds it
out: `DEFAULT` → `PROTECTED` is ABI-compatible for normal callers but
silently defeats `LD_PRELOAD` interposition.

### Symbol Versioning

A version script (`-Wl,--version-script=libfoo.map`) groups symbols into
named nodes like `LIBFOO_1.0`, recorded in `.gnu.version_d` and tagged in
`.gnu.versym`; consumers carry matching `.gnu.version_r` entries. This lets
one `.so` ship multiple ABI generations side by side.
[Case 13](../../examples/case13_symbol_versioning/README.md) shows that
*adding* a version script is backward compatible — old binaries have no
`DT_VERNEED`, so `ld.so` resolves by name.
[Case 65](../../examples/case65_symbol_version_removed/README.md) is the
opposite: once a node has shipped, removing it deletes every symbol it
tagged. glibc's `GLIBC_2.0` has been append-only since 1997 — which is
why modern binaries still load on decade-old systems, and why OpenSSL
3.0's version-node removals forced the SONAME bump from `libssl.so.1.1`
to `.so.3`.

### Calling Conventions

A calling convention is the register-and-stack contract: which registers
hold args, which are callee-saved, and how the return comes back. On
x86-64 the two you meet are System V AMD64 (Linux/macOS/BSD, args in
`rdi, rsi, rdx, rcx, r8, r9`) and Microsoft x64 (Windows or via
`__attribute__((ms_abi))`, args in `rcx, rdx, r8, r9`). On 32-bit x86 the
zoo is larger: `cdecl`, `stdcall`, `fastcall`, `thiscall`, `vectorcall`.
[Case 64](../../examples/case64_calling_convention_changed/README.md) shows
the attribute flipping silently: the v1 caller loads pointers into
`rdi`/`rsi`, the v2 `ms_abi` callee reads `rcx`/`rdx`, and the function
operates on stale register contents — zero results or a segfault.
`abicheck` catches it by diffing the `DW_AT_calling_convention` DWARF
attribute; the signature is unchanged, so name-and-type-only checks miss
it.

### Security Metadata

The `PT_GNU_STACK` program header advertises whether the process stack
must be executable, and the linker unions it across input objects — so a
single assembly file missing its `.note.GNU-stack` annotation promotes the
entire `.so` (and every process that loads it) to an executable stack.
[Case 49](../../examples/case49_executable_stack/README.md) shows
`readelf -l` reporting `RWE` instead of `RW`; rpmlint and Debian lintian
both reject the package.
`DT_RPATH`/`DT_RUNPATH` hold extra linker search paths.
[Case 52](../../examples/case52_rpath_leak/README.md) shows a build system
baking `/home/build/myproject/lib` into the artifact: it only works on the
build host, and anyone who can write that path gets a library-injection
primitive. Use `$ORIGIN`-relative paths or strip `RPATH` entirely.

### Language Linkage and TLS

[Case 66](../../examples/case66_language_linkage_changed/README.md) covers
`extern "C"` removal during a C++ modernization: source still compiles,
but the `.dynsym` symbol flips from unmangled `parse_config` to mangled
`_Z12parse_configPKc`, and every pre-linked consumer fails at load time.
Treat `extern "C"` blocks as part of the public ABI.
TLS has four access models: `global-dynamic` (default for `.so`,
`dlopen`-safe), `local-dynamic`, `initial-exec` (faster but requires
presence at startup — `dlopen` fails), and `local-exec` (main executable
only). Libraries intended for `dlopen` must avoid `initial-exec`.
[Case 67](../../examples/case67_tls_var_size_changed/README.md) adds a
second hazard: any exported `__thread` struct whose layout shifts corrupts
consumers per-thread. Freeze size, layout, and access model of TLS exports
as first-class ABI.

> **Best practice**
>
> - **Version scripts as the source of truth.** A `.map` file enumerating
>   every intentional export is the canonical place to negotiate API surface.
> - **`ABI_EXPORT` macro discipline.** Build with `-fvisibility=hidden` and
>   annotate public functions with a project-specific macro.
> - **CI gate: `abicheck` on every PR.** Dump the previous release, compare
>   the candidate, fail on any `BREAKING` not paired with a SONAME bump.
> - **Never link with absolute `--rpath`.** Use `$ORIGIN` or install-time
>   rewriting; absolute build paths are non-portable and a security hazard.
> - **Declare TLS access models explicitly.** If a TLS variable is ever
>   reached via `dlopen`, pin `-ftls-model=global-dynamic`.

## Part 5: Subtle and Transitive Breaks

<!-- filled by agent 6 -->
