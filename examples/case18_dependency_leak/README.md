# Case 18 — Dependency ABI Leak

## What changes

`libfoo`'s **exported symbol interface** is identical between v1 and v2 — same function
names, same signatures. The breaking change is in `ThirdPartyHandle`, a type from a third-party library
that `libfoo` **exposes in its public header**.

| Version | `ThirdPartyHandle` layout |
|---------|--------------------------|
| v1 | `{ int x; }` → sizeof = 4 bytes |
| v2 | `{ int x; int y; }` → sizeof = 8 bytes |

## What breaks at binary level

A caller compiled with v1 headers allocates `ThirdPartyHandle h = {42}` — 4 bytes.
It passes `&h` to `process()`. The v2 `.so` was compiled with the new layout and
may access `h->y` (at offset 4) — reading garbage or unmapped memory.

Even if `libfoo` itself doesn't access `y`, the caller's `sizeof(ThirdPartyHandle)`
mismatch means array indexing is wrong:
```c
ThirdPartyHandle arr[10];  // caller: 40 bytes total
                            // library: expects 80 bytes (10 × 8)
```

**libfoo's exported symbol table looks identical** in both scenarios. `nm`, `readelf`,
and naive `abidiff` see the same function names and signatures. Only the headers changed.
`nm`, `readelf`, and naive `abidiff` see no difference in the `.so`.

## Why abidiff may catch it (with DWARF)

If `libfoo` is compiled with `-g`, DWARF records `ThirdPartyHandle`'s layout.
`abidiff` comparing v1 and v2 `.so` files would detect the type size change — but
**only if the third-party type is transitively included in the DWARF** of `libfoo.so`.
Many distributions strip debug info, making this invisible to abidiff.

## Why ABICC catches it

ABICC processes all headers transitively, including `thirdparty.h`. It computes AST
diffs across the entire header graph. When `ThirdPartyHandle` changes size, ABICC
reports it as a type layout change that affects the ABI of `libfoo`'s exported functions.

## Real-world example

**Intel oneDAL** includes `tbb::task_arena` (a TBB type) in some public headers.
When Intel TBB changed `task_arena`'s internal layout in TBB 2021.3, oneDAL's ABI
broke for users who had TBB 2021.2 installed. The `.so` files hadn't changed.

**Protocol Buffers (protobuf)**: Several gRPC components include `grpc::Status` which
internally holds `std::string`. When libstdc++ changed `std::string` ABI (GCC 5.x,
CXX11 ABI), all libraries exposing `grpc::Status` in their public headers broke
silently. This is why Abseil and gRPC now use opaque handle types.

## Best practice

> **Never expose implementation-detail types in your public API headers.**

Use the **Pimpl idiom** or **opaque handles**:

```c
/* BAD: ThirdPartyHandle leaks into public API */
void process(ThirdPartyHandle* h);

/* GOOD: opaque handle — caller never sees ThirdPartyHandle */
typedef struct foo_handle foo_handle_t;
foo_handle_t* foo_create(int x);
void          foo_process(foo_handle_t* h);
void          foo_destroy(foo_handle_t* h);
```

See also the **Dependency ABI Leaks** section in `examples/README.md`.

## Code diff

```diff
-/* thirdparty.h v1 */
-typedef struct { int x; } ThirdPartyHandle;

+/* thirdparty.h v2 */
+typedef struct { int x; int y; } ThirdPartyHandle;  /* struct grew */

 /* foo.h — unchanged source */
 void process(ThirdPartyHandle* h);
```

## Reproduce steps

```bash
cd examples/case18_dependency_leak

# Build libfoo v1 and v2 (source identical, different thirdparty headers)
gcc -shared -fPIC -g libfoo_v1.c -I. -o libfoo_v1.so
gcc -shared -fPIC -g libfoo_v2.c -I. -o libfoo_v2.so

# Compare the .so files — they look identical at symbol level
nm --dynamic libfoo_v1.so
nm --dynamic libfoo_v2.so
diff <(nm --dynamic libfoo_v1.so) <(nm --dynamic libfoo_v2.so) || true

# abidiff WITH DWARF may catch ThirdPartyHandle layout change
abidw --out-file foo_v1.xml libfoo_v1.so
abidw --out-file foo_v2.xml libfoo_v2.so
abidiff foo_v1.xml foo_v2.xml || true

# ABICC catches via transitive header AST diff
abi-compliance-checker -lib libfoo -v1 1.0 -v2 2.0 \
  -header foo_v1.h -header foo_v2.h \
  -include-path . \
  -gcc-options "-I."
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** app allocates `ThirdPartyHandle` with v1 layout (4 bytes), calls `process()` from v2 which reads `h->y` at offset 4 — uninitialized memory.

```bash
# Build libfoo v1 + app
gcc -shared -fPIC -g libfoo_v1.c -I. -o libfoo.so
gcc -g app.c -I. -L. -lfoo -Wl,-rpath,. -o app
./app
# → h.x = 42, sizeof(h) = 4
# → process: x=42
# → after process: h.x = 42

# Swap in libfoo v2 (compiled with ThirdPartyHandle = {int x, int y})
gcc -shared -fPIC -g libfoo_v2.c -I. -o libfoo.so
./app
# → h.x = 42, sizeof(h) = 4
# → process: x=42
# → process: y=32764  ← GARBAGE (reads 4 bytes past caller's allocation)
# → after process: h.x = 42
```

**Why CRITICAL:** The library's exported symbol table looks identical in both scenarios —
`nm` and `readelf` show the same function names. Yet the v2 library reads 4 bytes past the
caller's struct allocation because the third-party type it exposes in its public header
grew silently. Heap corruption or information leakage follows.
