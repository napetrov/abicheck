# Full ABI/API breakage guide for `examples/case01..case24`

This document explains every example case with practical detail:

1. a **code-style example** of the change,
2. a paragraph describing **why compatibility is broken**,
3. a note on **how to avoid the break**.

The examples are intentionally minimal and illustrative. They are not byte-for-byte copies
of the repository files, but they mirror the exact compatibility pattern each case demonstrates.

---

## case01_symbol_removal — exported symbol removed

```c
/* v1 */
int foo_init(void);
/* v2 */
/* removed */
```

When a previously exported symbol disappears, older binaries that were linked against that symbol
still try to resolve it at runtime. The dynamic loader fails with `undefined symbol`, and the
application may fail to start before `main()` executes. This is one of the clearest hard ABI
breaks because the consumer binary itself was valid at build time but becomes unloadable against
new library bits. Avoid this by keeping the old entry point as a wrapper (even if deprecated)
or removing it only in a major release with SONAME bump and migration path.

## case02_param_type_change — function parameter type changed

```c
/* v1 */
int parse_value(int x);
/* v2 */
int parse_value(long x);
```

Changing parameter types changes the calling contract at ABI level: register width, stack layout,
and argument classification can differ between `int` and `long` (especially cross-arch). Old callers
pass one ABI shape while new callee expects another, which can yield corrupted inputs or undefined
behavior. Even if source code recompiles cleanly, already-built downstream artifacts can misbehave.
Safer evolution is to keep the old function and add `parse_value_v2(long x)`.

## case03_compat_addition — compatible symbol addition

```c
/* v1 */
int api_do_work(void);
/* v2 */
int api_do_work(void);
int api_get_version(void); /* new */
```

Adding a new symbol is usually backward-compatible because old consumers do not require it.
Previously built binaries continue to find every symbol they used, and new functionality is opt-in.
The compatibility risk here is policy-level, not immediate ABI failure: if additions expose unstable
internals, future lock-in can happen. Keep additions namespaced/versioned and document stability
status to avoid accidental contract expansion.

## case04_no_change — unchanged baseline

```c
/* v1 and v2 */
int stable_add(int a, int b);
```

This case validates the tooling baseline and guards against false positives. No signature, layout,
or export changes means both API and ABI should compare as unchanged. If this case ever reports
breakage, your detection setup, headers, or build flags are inconsistent. Keep a no-change test
in CI to continuously verify the checker itself and prevent noisy regressions in compatibility gates.

## case05_soname — SONAME policy regression

```bash
# good
gcc -shared -Wl,-soname,libfoo.so.2 -o libfoo.so.2 foo.c
# bad: SONAME missing or unchanged after ABI break
```

SONAME is the loader-level contract for binary compatibility lines. If ABI breaks but SONAME is not
updated, package managers and runtime linkers may silently substitute incompatible builds under the
same logical dependency. This causes hard-to-debug production failures because deployment appears
successful while runtime behavior is broken. Keep SONAME discipline strict: incompatible ABI change
must produce a new SONAME, and package metadata should track it.

## case06_visibility — internal symbol leakage

```c
/* intended internal */
int helper_internal(int x);  /* accidentally exported */
```

When internal functions leak into the export table, downstream users may start linking against them.
At that moment they become de facto public ABI, even if never documented. Later refactors then break
those accidental consumers and create compatibility pressure on implementation details. Use
`-fvisibility=hidden` globally and explicit export annotations for true public API only.

## case07_struct_layout — struct field/layout changed

```c
/* v1 */
struct Config { int a; int b; };
/* v2 */
struct Config { int a; long b; }; /* size/alignment changed */
```

Public struct layout is part of ABI because callers allocate and access fields using compile-time
offset assumptions. If size/alignment/offset changes, old code writes to wrong memory locations,
triggering data corruption or crashes. This is especially dangerous for stack-passed structs and FFI.
To avoid this, keep public structs stable or hide representation behind opaque pointers and versioned
constructor/accessor APIs.

## case08_enum_value_change — enum numeric values changed

```c
/* v1 */
enum Mode { MODE_OFF = 0, MODE_ON = 1 };
/* v2 */
enum Mode { MODE_OFF = 1, MODE_ON = 2 };
```

Even when type names are unchanged, numeric enum values are wire-level semantics. Persisted data,
RPC payloads, switch statements, and external integrations may rely on exact numbers. Reassigning
values turns valid old state into new meaning and causes silent logic corruption rather than obvious
linker failures. Treat enum numbers as immutable once released; only append new members.

## case09_cpp_vtable — virtual interface changed

```cpp
// v1
struct I { virtual void a(); virtual void b(); };
// v2
struct I { virtual void b(); virtual void a(); }; // reordered
```

C++ virtual dispatch depends on stable vtable slot ordering/signatures. Reordering or changing
virtual methods changes slot mapping, so an old binary call to `a()` can dispatch into `b()` or a
different thunk in new library builds. This is a classic catastrophic C++ ABI break: code runs but
calls wrong behavior. Preserve virtual ABI by freezing interface layout or introducing new interface
versions (`I2`) instead of mutating old ones.

## case10_return_type — return type changed

```c
/* v1 */
int get_count(void);
/* v2 */
long get_count(void);
```

Return type affects ABI-level return registers, sign extension, and caller expectations. An old
caller compiled for `int` may interpret only part of a larger return, while a new callee writes a
different shape. These mismatches can produce truncation or undefined behavior with no compile-time
warning for already built clients. Keep old symbol and add a versioned alternative with explicit
name change.

## case11_global_var_type — global variable type changed

```c
/* v1 */
extern int g_state;
/* v2 */
extern long g_state;
```

Public globals are ABI surface too: size, alignment, and access codegen are fixed in consumers.
Changing type of an exported variable means old code reads/writes with the wrong width and memory
assumptions. The result can be silent memory clobbering near adjacent globals. Prefer accessor
functions over mutable exported globals, and treat existing globals as frozen contracts.

## case12_function_removed — public function removed

```c
/* v1 */
int run_task(int id);
/* v2 */
/* removed */
```

Removing a function symbol is equivalent to removing any required import from consumer binaries.
Existing applications fail symbol resolution immediately when loaded with new library version.
Unlike source-level changes, downstream teams may not recompile right away, so this causes direct
runtime outages. Deprecate first, keep a forwarding stub, and remove only in a planned ABI-major cut.

## case13_symbol_versioning — symbol version map regression

```map
# v1 map
LIBFOO_1.0 { global: api_*; local: *; };
# v2 bad: map removed or changed incompatibly
```

Symbol versioning distinguishes ABI generations for identical names and enables controlled upgrades.
If version scripts are removed or regressed, loaders can no longer resolve intended versions cleanly,
especially across distro backports or mixed dependency trees. This causes subtle runtime resolution
issues that are painful to debug. Keep version scripts in source control and validate exported
versions in CI.

## case14_cpp_class_size — C++ class object size changed

```cpp
// v1
class Obj { int x; };
// v2
class Obj { int x; int y; }; // sizeof changed
```

For by-value usage, embedded members, allocators, and placement new patterns, object size is ABI
critical. Old code allocates `sizeof(v1::Obj)` while new library may expect larger object layout,
leading to overwrites and corruption. This often appears as random crashes far from call sites.
Use Pimpl for public classes to keep externally visible object size constant across releases.

## case15_noexcept_change — exception contract changed

```cpp
// v1
int process() noexcept;
// v2
int process();
```

In C++, `noexcept` is part of the function type/signature model and affects optimization and
behavioral guarantees. Mixed old/new object sets can disagree on exception behavior, potentially
triggering termination paths or violating caller assumptions in generic code. Some binary tools miss
this because it is semantic rather than simple symbol presence. Treat `noexcept` as stable API/ABI
contract and evolve through new symbols when needed.

## case16_inline_to_non_inline — inline/ODR behavior changed

```cpp
// v1 header
inline int mul2(int x) { return x * 2; }
// v2
int mul2(int x); // moved out-of-line
```

Switching inline strategy changes where code is emitted and how ODR/linking behaves across
translation units compiled at different times. Old consumers may have inlined old behavior while new
ones call exported symbol, creating mixed semantics in one process. In some transitions, you also
introduce/remove required dynamic symbols unexpectedly. Keep inline policy stable for public headers
or version such changes explicitly.

## case17_template_abi — template instantiation ABI drift

```cpp
// v1
template<class T> struct Box { T v; int tag; };
// v2
template<class T> struct Box { T v; long tag; };
```

Template types instantiate into concrete layouts in consumer translation units. Changing template
layout means independently compiled modules disagree about object representation for the same source
name, causing cross-module corruption and ODR-like failures. This is common in header-only APIs.
Avoid exposing unstable templates in ABI boundaries; hide them behind non-template façade types.

## case18_dependency_leak — third-party type leaks into public API

```cpp
// public header
#include <thirdparty/task_arena.hpp>
struct ApiCfg { thirdparty::Arena arena; }; // leaked dependency type
```

If public API embeds a third-party type, your ABI now depends on that external library's private
layout/version policy. Upgrading the dependency can break your consumers even when your own `.so`
binary is unchanged, because callers compile different structure definitions. This is a transitive
ABI break and a common enterprise packaging trap. Use opaque boundaries and internal adapters to keep
third-party ABI out of your public headers.

## case19_enum_member_removed — enum member removed

```c
/* v1 */
enum Level { LOW=0, MED=1, HIGH=2 };
/* v2 */
enum Level { LOW=0, HIGH=2 }; // MED removed
```

Removing enum members breaks compatibility with persisted values, logs, protocol fields, and old
switch statements that still produce/use removed constants. Even if binaries load, semantic mapping
becomes incomplete and behavior may diverge silently. Keep historical enum members, mark them
deprecated, and document replacement behavior rather than deleting values.

## case20_enum_member_value_changed — enum member numeric reassigned

```c
/* v1 */
enum Status { OK=0, FAIL=1 };
/* v2 */
enum Status { OK=1, FAIL=2 };
```

Reassigning existing enum numbers is equivalent to changing protocol constants in place.
Downstream components serialized with old values decode into wrong states under new headers/binaries,
causing cross-version interoperability failure. This is especially severe for network/storage formats.
Keep numeric assignments stable forever and introduce new names for new semantics.

## case21_method_became_static — instance method changed to static

```cpp
// v1
struct S { int calc(int x) const; };
// v2
struct S { static int calc(int x); };
```

Instance vs static methods are ABI-distinct in C++: implicit `this` parameter presence and mangled
name differ. Old callers emit calls expecting member-function ABI, but new library provides a
different symbol/call shape. This breaks linking and/or invocation expectations. Keep old method and
add static helper under a new name.

## case22_method_const_changed — member const qualifier changed

```cpp
// v1
struct S { int size() const; };
// v2
struct S { int size(); };
```

`const` qualification on member methods is encoded in C++ symbol identity and overload sets.
Changing it in place replaces one symbol with another, so old binaries can no longer resolve the
original mangled entry point. It can also alter overload resolution in source consumers. Preserve old
qualified method and add a new overload or differently named API.

## case23_pure_virtual_added — new pure virtual method added

```cpp
// v1
struct IFace { virtual void run() = 0; };
// v2
struct IFace { virtual void run() = 0; virtual void stop() = 0; };
```

Adding a pure virtual method changes vtable shape and instantly breaks all existing derived classes
compiled against old interface: they do not implement new slot and may become abstract or dispatch
incorrectly. This is one of the highest-impact C++ ABI changes in plugin ecosystems. Introduce a new
interface version (`IFace2`) and keep original interface frozen.

## case24_union_field_removed — union field removed

```c
/* v1 */
union Value { int i; float f; };
/* v2 */
union Value { int i; }; // f removed
```

Union members define valid interpretations of shared storage. Removing a field changes what old code
can legally read/write and may invalidate serialized or exchanged data assumptions. Even when union
size stays equal, semantic ABI is broken because one representation disappears. Keep union contracts
stable or replace with a new versioned type and explicit conversion path.

---

## Global compatibility practices

- Treat public headers as ABI contracts, not implementation convenience.
- Use SONAME + symbol versioning + visibility controls as mandatory release gates.
- Prefer opaque handles/Pimpl over exposing mutable layouts.
- Evolve via additive, versioned APIs; avoid in-place mutations of released contracts.
- Run these example patterns in CI as a required ABI regression suite.
