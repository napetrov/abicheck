# Case 44: Cyclic Type Member Added

**Category:** Struct Layout | **Verdict:** 🔴 BREAKING

## What breaks
`Node` is a self-referential linked-list struct: it contains a pointer to itself
(`struct Node *next`). A new `long priority` field is added in v2. On a 64-bit
system the existing padding between `flags` and `next` is consumed, growing
`sizeof(Node)` from 16 to 24 bytes.

`node_sum()` accepts `Node` **by value** — so the struct size is directly part of
the calling convention. Callers compiled with v1 push 16 bytes onto the stack;
the v2 library reads 24 bytes, interpreting stack garbage as `priority`.

## Why abidiff catches it
abidiff reads DWARF and detects the size increase on the cyclic type:

- `TYPE_SIZE_CHANGED` on `Node` (16 → 24 bytes on 64-bit)
- `TYPE_FIELD_ADDED`: `long priority` at offset 8
- Exit code **4** (ABI change, non-removal break)

The cyclic pointer (`Node *next`) does not confuse abidiff — it resolves the
recursion and still correctly reports the outer-struct size change.

## Code diff

| v1.h | v2.h |
|------|------|
| `typedef struct Node { int data; int flags; struct Node *next; } Node;` | `typedef struct Node { int data; int flags; long priority; struct Node *next; } Node;` |
| `sizeof(Node) == 16` (on 64-bit) | `sizeof(Node) == 24` (+8 bytes) |

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile caller against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 library + caller
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g -I. app.c -L. -lv1 -Wl,-rpath,. -o app
./app
# → sum = 3  (correct)

# Swap in v2 library (no recompile)
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# → sum = <wrong> or crash: by-value arg passes 16-byte frame, lib reads 24 bytes
```

**Why CRITICAL:** The by-value call passes `sizeof(Node)` bytes as determined at
compile time. The v2 function reads past the caller's stack frame to access
`priority`, producing an arbitrary value or a stack-smashing crash.

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
1. **Never pass structs by value in public APIs.** Use pointers (`Node *`) so the
   caller never needs to know `sizeof(Node)`.
2. **Opaque handle pattern** — expose only `Node *` and keep the struct definition
   in the `.c` file (not the header).
3. **Reserve padding** — add `char _reserved[8]` to absorb one extra field without
   changing the size.
4. **SONAME bump** — if the change is unavoidable and by-value is required, bump
   the major version and force recompilation.
