# Case 28 — Typedef and Opaque Type Changes

**Category:** Type System | **Verdict:** 🔴 BREAKING (TYPEDEF_BASE_CHANGED, TYPEDEF_REMOVED, TYPE_BECAME_OPAQUE)

## What changes

| Symbol / Type | v1 | v2 | Effect |
|---|---|---|---|
| `dim_t` | `typedef int dim_t` | `typedef long dim_t` | Size 4 → 8 bytes (LP64) |
| `handle_t` | `typedef unsigned int handle_t` | *(removed)* | Source break |
| `struct Context` | Complete (id, flags, name[32]) | Forward declaration only | Opaque — no stack alloc |

## Why this IS a binary ABI break

1. **TYPEDEF_BASE_CHANGED (`dim_t`):** The return type of `get_dimension()` changes from
   `int` (4 bytes, returned in lower 32 bits of `%eax`) to `long` (8 bytes, full `%rax`).
   Callers compiled against v1 treat the return as `int` and may truncate or misinterpret
   the value. If `dim_t` is used in structs, their layout changes silently.

2. **TYPEDEF_REMOVED (`handle_t`):** Code using `handle_t` will not compile against v2.
   At the binary level `create_handle()` still exists (returns `unsigned int`), so
   already-compiled binaries continue to link. This is a **source-only** break.

3. **TYPE_BECAME_OPAQUE (`struct Context`):** v1 exposes the full struct definition,
   allowing stack allocation and direct field access. v2 provides only a forward
   declaration. Existing binaries that stack-allocate `Context` or access its fields
   inline will silently corrupt memory if the internal layout ever changes.

## Code diff

```diff
-typedef int dim_t;
+typedef long dim_t;

-typedef unsigned int handle_t;
+/* removed */

-struct Context {
-    int id;
-    int flags;
-    char name[32];
-};
+struct Context;   /* opaque forward declaration */
```

## Real Failure Demo

**Severity: HIGH**

**Scenario:** Compile app against v1 headers, then swap in the v2 `.so` without recompiling.

```bash
# Build v1 library + app
gcc -shared -fPIC -g v1.c -o libfoo.so
gcc -g app.c -I. -L. -lfoo -Wl,-rpath,. -o app
./app
# → Scenario 1 — dim_t base type change:
# →   sizeof(dim_t) at compile time = 4 (expected 4 for int)
# →   get_dimension(7) = 7
# →   If v2 lib loaded: dim_t is long (8 bytes) but caller expects int (4 bytes)
# →
# → Scenario 2 — handle_t typedef removed:
# →   create_handle() = 42
# →   Binary still works (function exists), but recompilation against v2.h fails
# →
# → Scenario 3 — struct Context became opaque:
# →   sizeof(struct Context) at compile time = 40
# →   Stack-allocated Context: id=99 flags=0x1 name="stack-ctx"
# →   With v2 header this code would NOT compile (incomplete type)

# Swap in v2 library (no recompile of app)
gcc -shared -fPIC -g v2.c -o libfoo.so
./app
# → Output looks identical — but dim_t return is now 8 bytes wide;
# → the caller only reads 4 bytes. On LP64 this happens to work for
# → small values but is technically undefined behavior.
```

**Source break verification** (recompilation against v2 fails):

```bash
gcc -g app.c -I. -include v2.h -L. -lfoo -Wl,-rpath,. -o app_v2 2>&1
# → error: 'handle_t' undeclared
# → error: invalid application of 'sizeof' to incomplete type 'struct Context'
# → error: variable 'local' has initializer but incomplete type
```

## Reproduce with abicheck

```bash
gcc -shared -fPIC -g v1.c -o libfoo_v1.so
gcc -shared -fPIC -g v2.c -o libfoo_v2.so
abidw --out-file v1.xml libfoo_v1.so
abidw --out-file v2.xml libfoo_v2.so
abidiff v1.xml v2.xml
echo "exit: $?"
```

## How to fix

- **typedef base change:** Never change the underlying type of a public typedef.
  Introduce a new typedef (`dim64_t`) and deprecate the old one.
- **typedef removal:** Keep the old typedef as an alias (`typedef unsigned int handle_t;`)
  until the next major SONAME bump.
- **opaque transition:** Provide the full struct definition in a separate "internal" header
  and only expose the opaque pointer in the public API from the start.
