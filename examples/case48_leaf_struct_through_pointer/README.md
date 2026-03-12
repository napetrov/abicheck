# Case 48: Leaf Struct Change Propagated Through Pointer

**Category:** Struct Layout | **Verdict:** 🔴 BREAKING

## What breaks
`Leaf` gains a new `int z` field, growing from 4 bytes to 8 bytes. `Leaf` is embedded
(not pointed to) inside `Container` at offset 4. Because `Leaf` grew by 4 bytes,
`Container::flags` shifts from offset 8 to offset 12, and `sizeof(Container)` grows
from 12 to 16 bytes.

The public API only takes `Container *` — no by-value `Container` or `Leaf` in any
signature. But any caller that has `Container` on the stack (e.g. `Container c;
container_init(&c, ...);`) allocates it with the v1 size (12 bytes). The v2 library
writes `flags` 4 bytes further than the caller's allocation, overflowing the stack
object and corrupting adjacent memory.

## Why abidiff catches it
abidiff follows the embedded `Leaf` type through `Container` and detects the cascading
layout change:

- `TYPE_SIZE_CHANGED` on `Leaf` (4 → 8 bytes)
- `TYPE_FIELD_ADDED` on `Leaf`: `int z` at offset 4
- `TYPE_SIZE_CHANGED` on `Container` (12 → 16 bytes)
- `TYPE_FIELD_OFFSET_CHANGED` on `Container::flags` (offset 8 → 12)
- Exit code **4** (ABI change detected)

## Code diff

| v1.h | v2.h |
|------|------|
| `typedef struct Leaf { short x; short y; } Leaf;` (4 bytes) | `typedef struct Leaf { short x; short y; int z; } Leaf;` (8 bytes) |
| `Container::flags` at byte offset 8 | `Container::flags` at byte offset 12 |
| `sizeof(Container) == 12` | `sizeof(Container) == 16` |

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile caller against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 library + caller
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g -I. app.c -L. -lv1 -Wl,-rpath,. -o app
./app
# → flags = 7, position = (10, 20)  (correct)

# Swap in v2 library (no recompile)
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# → flags = <garbage>: container_init() writes flags 4 bytes past the caller's 12-byte allocation
# → or: SIGSEGV / stack corruption depending on surrounding variables
```

**Why CRITICAL:** The caller allocates a 12-byte `Container` (v1 layout). The v2
`container_init()` writes `flags` at byte 12, which is outside the allocated 12-byte
region — corrupting adjacent stack memory. This is a stack-buffer overflow caused
purely by a leaf struct growing silently.

## Reproduce manually
```bash
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so
abidw --out-file v1.xml libv1.so
abidw --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 4
```

## How to fix
1. **Pimpl for `Leaf`** — forward-declare `Leaf` in the public header and expose it
   only as an opaque pointer; define it fully in the `.c` file. Adding fields to the
   private definition does not affect `Container`'s public layout.
2. **Reserve padding in `Leaf`** — add `char _reserved[4]` to absorb one future
   `int`-sized field without changing the struct size.
3. **Opaque accessor pattern** — instead of embedding `Leaf` by value in `Container`,
   use `Leaf *position` (pointer). The pointer size (8 bytes on 64-bit) stays fixed
   regardless of `Leaf`'s internals.
4. **SONAME bump** — if the layout change is necessary and cannot be hidden, bump the
   major version (`libfoo.so.2`) and require recompilation of all consumers.
