# Full ABI/API breakage guide for `examples/case01..case24`

This guide is intentionally verbose. Every case includes:

- a minimal **v1 vs v2** change snippet,
- a **consumer-side example** showing how downstream code is affected,
- a detailed explanation of **why** compatibility is broken,
- practical mitigation strategies.

---

## case01_symbol_removal — exported symbol removed

```c
/* lib v1 */
int foo_init(void);

/* lib v2 */
/* int foo_init(void); removed */
```

```c
/* consumer (built against v1) */
extern int foo_init(void);
int main(void) { return foo_init(); }
```

If `foo_init` is removed from the dynamic symbol table, the consumer binary still contains an import
for that symbol and expects the loader to resolve it from the shared object. With v2 installed, symbol
resolution fails before application logic starts, typically with `undefined symbol: foo_init`. This is
a hard ABI break because the already-built consumer artifact becomes non-runnable without recompilation.

To avoid this, keep the old symbol as a compatibility wrapper (possibly deprecated) and forward it to
new implementation. Remove only in a major ABI line and bump SONAME so package managers and users can
co-install or consciously migrate.

## case02_param_type_change — parameter ABI changed

```c
/* lib v1 */
int parse_value(int x);

/* lib v2 */
int parse_value(long x);
```

```c
/* consumer */
extern int parse_value(int);
int run(void) { return parse_value(42); }
```

Parameter type changes alter the call contract. Even when both types are integral, ABI rules may differ
in width/sign extension/register class on different targets. An old caller compiled for `int` can pass
bits that the new callee interprets as `long`, leading to value corruption or undefined behavior. The
symbol name might stay “the same” in C, but call semantics are not.

Safe evolution pattern: keep `parse_value(int)` and introduce `parse_value_v2(long)`. Route old API to
new internals where possible, but preserve old symbol and signature for binary stability.

## case03_compat_addition — additive symbol

```c
/* lib v1 */
int api_do_work(void);

/* lib v2 */
int api_do_work(void);
int api_get_version(void); /* new */
```

```c
/* old consumer */
extern int api_do_work(void);
```

Adding a new symbol usually does not break old consumers because they do not import it. Their original
imports are still present and resolvable, so load-time and call-time behavior remains compatible.
However, additions can still create long-term API surface commitments if they expose internals.

Best practice is to mark stability level, document lifecycle, and ensure added APIs do not leak private
layout types or unstable dependencies.

## case04_no_change — baseline control

```c
/* lib v1 */
int stable_add(int a, int b);
/* lib v2 */
int stable_add(int a, int b);
```

```c
/* consumer */
extern int stable_add(int, int);
```

No signature/layout/export changes means ABI should be identical. This case is important because it
validates the checker pipeline itself: if “no change” reports breakage, either comparison inputs are
mismatched (headers/flags/tool mode) or detection logic regressed.

Keep this case in CI as a guardrail against false positives and noisy policy failures.

## case05_soname — SONAME policy violation

```bash
# good release line
gcc -shared -Wl,-soname,libfoo.so.2 -o libfoo.so.2 foo.c

# bad release line
# ABI changed, but SONAME left as libfoo.so.1 (or omitted)
```

```bash
# consumer links to libfoo.so.1 in package metadata
ldd app
```

SONAME communicates ABI lineage to loaders and package tools. If ABI changes but SONAME does not, the
system can silently replace a previously compatible dependency with an incompatible one under the same
name. Failures then appear at runtime and are often misdiagnosed as environment issues.

Treat SONAME as mandatory release policy: incompatible ABI => SONAME bump + explicit migration notes.

## case06_visibility — accidental export leak

```c
/* intended internal helper */
int helper_internal(int x); /* accidentally exported in v1 */
```

```c
/* third-party consumer (undesired) */
extern int helper_internal(int);
```

When internal functions leak into exports, external users may start linking against them. That turns
implementation detail into de facto public ABI, even if undocumented. Removing or changing it later
breaks those consumers and locks your internals.

Use hidden visibility by default (`-fvisibility=hidden`) and explicitly export only supported public
entry points with an API macro.

## case07_struct_layout — public struct layout drift

```c
/* v1 */
struct Config { int a; int b; };

/* v2 */
struct Config { int a; long b; };
```

```c
/* consumer compiled with v1 header */
struct Config c = {1, 2};
lib_use_config(&c);
```

Public struct layout is ABI: field offsets, total size, and alignment are baked into consumer codegen.
If the library now reads `b` at a different offset/width, old callers pass memory in an outdated shape.
That can corrupt adjacent memory or produce nonsense values, especially across FFI boundaries.

Avoid by freezing public structs or hiding representation behind opaque handles and accessor functions.

## case08_enum_value_change — semantic wire break

```c
/* v1 */
enum Mode { MODE_OFF = 0, MODE_ON = 1 };

/* v2 */
enum Mode { MODE_OFF = 1, MODE_ON = 2 };
```

```c
/* consumer persisted old value 1 meaning MODE_ON */
write_mode_to_disk(MODE_ON);
```

Enum values are often protocol constants. Reassigning numbers changes semantics for persisted state,
network payloads, and cross-service interoperability. The program may still compile and run, but logic
silently diverges because “same name” maps to different integer meaning.

Never renumber released enum constants; append new values only.

## case09_cpp_vtable — virtual dispatch ABI break

```cpp
// v1
struct I {
  virtual void a();
  virtual void b();
};

// v2
struct I {
  virtual void b();
  virtual void a();
};
```

```cpp
// consumer compiled with v1 expectations
I* p = get_iface();
p->a();
```

Vtable slot ordering and signature thunks are part of C++ ABI. Reordering methods changes slot-to-
method mapping; old binaries may call the wrong function through the same call site. This yields
catastrophic semantic corruption without obvious linker errors.

Freeze virtual interface ABI or introduce a new interface version (`I2`) instead of mutating v1.

## case10_return_type — return ABI mismatch

```c
/* v1 */
int get_count(void);

/* v2 */
long get_count(void);
```

```c
/* consumer */
extern int get_count(void);
int x = get_count();
```

Return type impacts register usage and value interpretation at call boundary. Old caller expects `int`,
new callee returns `long`; truncation/sign mismatch can occur and behavior becomes target-dependent.
Source-level compatibility after rebuild does not protect already deployed binaries.

Preserve old symbol and add `get_count_v2` with new type.

## case11_global_var_type — exported global contract changed

```c
/* v1 */
extern int g_state;

/* v2 */
extern long g_state;
```

```c
/* consumer */
extern int g_state;
int snapshot = g_state;
```

Global variables are ABI surface. Consumer load/store width and relocation assumptions are compiled in.
Changing variable type can cause partial writes/reads or neighboring memory corruption.

Prefer getter/setter API and keep existing exported globals immutable in type and semantics.

## case12_function_removed — hard symbol break

```c
/* v1 */
int run_task(int id);

/* v2 */
/* removed */
```

```c
/* consumer */
extern int run_task(int);
```

This is equivalent to case01 at policy level: import remains in old consumer binary, export is gone in
new library, loader fails. Runtime outage risk is high because users can hit breakage simply by package
upgrade, without changing their code.

Use deprecation windows and SONAME-major removal policy.

## case13_symbol_versioning — version-script regression

```map
# v1
LIBFOO_1.0 { global: api_*; local: *; };

# v2 (bad)
# script removed / version tags changed incompatibly
```

```bash
readelf --version-info libfoo.so
```

Symbol version tags disambiguate ABI generations and improve compatibility in mixed environments.
Regressing the map can cause incorrect symbol binding across distro backports or plugin ecosystems.
Failures may be subtle and environment-specific, making them expensive to debug.

Keep version scripts under strict CI checks and treat changes as ABI governance events.

## case14_cpp_class_size — object layout size break

```cpp
// v1
class Obj { int x; };

// v2
class Obj { int x; int y; };
```

```cpp
// consumer stack/heap allocation assumes v1 sizeof(Obj)
Obj o;
lib_accept_obj(&o);
```

For public classes, object size and field offsets are ABI. If a newer library expects larger layout,
old allocations can be too small, causing writes beyond boundaries. Crashes may appear far from origin.

Use Pimpl to keep public object footprint stable.

## case15_noexcept_change — behavioral ABI contract change

```cpp
// v1
int process() noexcept;

// v2
int process();
```

```cpp
// consumer generic code assumes noexcept contract
static_assert(noexcept(process()));
```

`noexcept` participates in function type semantics and influences optimization/error handling behavior.
Mixed object sets built with different assumptions can diverge in exception paths (including terminate).
This may evade symbol-only checks but still break real-world behavior contracts.

Treat `noexcept` as stable API commitment; evolve via new API version.

## case16_inline_to_non_inline — ODR/export behavior drift

```cpp
// v1 header
inline int mul2(int x) { return x * 2; }

// v2 header
int mul2(int x); // now out-of-line
```

```cpp
// old TU inlined old body; new TU links to symbol
```

Inline policy changes can create mixed semantics across translation units built at different times.
Some code paths embed old logic, others call new shared implementation. Depending on transition,
dynamic symbol set can also appear/disappear unexpectedly.

Keep public inline behavior stable, or version the API explicitly.

## case17_template_abi — instantiated layout mismatch

```cpp
// v1
template<class T> struct Box { T v; int tag; };

// v2
template<class T> struct Box { T v; long tag; };
```

```cpp
// module A and B compiled against different headers exchange Box<int>
```

Templates instantiate in user code, so layout changes propagate into every downstream build. Different
modules can disagree on representation for the same nominal type, causing corruption during boundary
crossing and serialization.

Avoid exposing unstable templates in ABI boundaries; provide non-template stable façade.

## case18_dependency_leak — transitive ABI dependency exposure

```cpp
// public API header
#include <thirdparty/task_arena.hpp>
struct ApiCfg { thirdparty::Arena arena; };
```

```cpp
// consumer and library built against different third-party versions
```

If public API embeds third-party types, your ABI is now coupled to another project's layout/versioning.
A third-party upgrade can break your consumers even when your own symbols are unchanged. This is a
common enterprise break pattern during distro refreshes.

Hide third-party types behind opaque wrappers and stable project-owned DTOs.

## case19_enum_member_removed — removed semantic state

```c
/* v1 */
enum Level { LOW=0, MED=1, HIGH=2 };

/* v2 */
enum Level { LOW=0, HIGH=2 };
```

```c
// old data contains MED=1
```

Removing enum members invalidates historical persisted/protocol values and old branch logic.
Runtime may still proceed, but state decoding becomes incomplete and behavior undefined by policy.

Keep historical values, deprecate in docs, and map legacy meaning deliberately.

## case20_enum_member_value_changed — value remap incompatibility

```c
/* v1 */
enum Status { OK=0, FAIL=1 };

/* v2 */
enum Status { OK=1, FAIL=2 };
```

```c
// remote peer sends 1 expecting FAIL, receiver treats as OK in changed mapping
```

Numeric remapping is effectively protocol rewrite without version negotiation. Old/new components can
exchange the same integer and interpret opposite semantics.

Never reassign released numbers; add new constants and introduce explicit protocol versioning.

## case21_method_became_static — member ABI identity changed

```cpp
// v1
struct S { int calc(int x) const; };

// v2
struct S { static int calc(int x); };
```

```cpp
// old consumer emits member call ABI with implicit this
S s; s.calc(7);
```

Static and instance methods have different mangling and call conventions (presence of implicit `this`).
Changing in place replaces one ABI endpoint with another. Old binaries fail to bind or invoke correctly.

Add static helper under new name; preserve old member API.

## case22_method_const_changed — mangled symbol changed

```cpp
// v1
struct S { int size() const; };

// v2
struct S { int size(); };
```

```cpp
// consumer compiled against const-qualified member symbol
```

Const qualification is part of C++ member function type and symbol identity. Changing it replaces the
old mangled symbol; existing binaries expecting const-qualified entry point cannot resolve new one.
It may also alter overload behavior for rebuilt source consumers.

Keep old method and add overload/new API variant.

## case23_pure_virtual_added — interface contract expansion break

```cpp
// v1
struct IFace { virtual void run() = 0; };

// v2
struct IFace { virtual void run() = 0; virtual void stop() = 0; };
```

```cpp
// old plugin class implements only run()
struct Plugin : IFace { void run() override; };
```

Adding pure virtual methods changes required interface and vtable shape. Existing implementations are
no longer complete for new base contract and can fail to instantiate or dispatch safely.

Create `IFace2` and keep original interface stable for existing plugins.

## case24_union_field_removed — representation set reduced

```c
/* v1 */
union Value { int i; float f; };

/* v2 */
union Value { int i; };
```

```c
// consumer stores float path
union Value v; v.f = 1.5f;
lib_consume(v);
```

Union fields define valid interpretations of shared storage. Removing one field removes a supported
representation and can invalidate persisted/exchanged data and branch logic relying on that variant.
Even if size stays constant, semantic compatibility is broken.

Prefer versioned replacement unions/structs plus explicit conversion rules.

---

## Global compatibility rules

1. Treat public headers as ABI contracts.
2. Use SONAME + symbol versioning + visibility policy on every release.
3. Prefer opaque handles/Pimpl to avoid exposing mutable layouts.
4. Evolve with additive/versioned APIs, not in-place mutation.
5. Keep these cases in CI as mandatory ABI regression checks.
