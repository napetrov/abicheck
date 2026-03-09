# Case 36 -- Anonymous Struct/Union Change

**abicheck verdict: BREAKING**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `struct Variant { int tag; union { int i; float f; }; };` (size 8) |
| v2 | `struct Variant { int tag; union { int i; double d; }; };` (size 16) |

## Why this is a binary ABI break

Changing `float f` to `double d` inside the anonymous union increases the union's
size from 4 bytes to 8 bytes. This changes the overall struct size from 8 to 16
bytes (with alignment padding). When the app allocates a `Variant` on the stack
using v1's sizeof (8 bytes), but the v2 library's functions expect 16-byte objects,
the mismatch can cause:

- Stack corruption if the library writes beyond the 8-byte allocation
- Wrong field offsets if the `i` member moves due to alignment changes
- Subtle data corruption in arrays of `Variant`

In this specific case, `variant_get_int()` just reads `v->i` so the simple
demo may still produce correct output, but the size mismatch is a real ABI
incompatibility that breaks in more complex scenarios (arrays, memcpy, etc.).

## Code diff

```diff
 struct Variant {
     int tag;
     union {
         int    i;
-        float  f;    /* 4 bytes -> union size = 4 */
+        double d;    /* 8 bytes -> union size = 8, struct gains padding */
     };
 };
```

## Real Failure Demo

**Severity: CRITICAL**

```bash
# Build v1 lib + app
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g app.c -I. -L. -lv1 -Wl,-rpath,. -o app
./app
# -> sizeof(Variant) = 8
# -> tag = 1, i = 42
# -> variant_get_int() = 42

# Swap to v2
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# -> sizeof(Variant) = 8    <-- app still uses v1's size!
# -> tag = 1, i = 42
# -> variant_get_int() = 42 <-- may work for simple reads, but layout mismatch exists
#
# The real danger: v2's sizeof(Variant) is 16, but the app allocated only 8 bytes.
# Any v2 library code that copies or iterates Variant arrays will corrupt memory.
```

**Why CRITICAL:** The struct size changed from 8 to 16 bytes. Even though simple
field reads may accidentally work, the layout mismatch is a ticking time bomb:
array indexing, `memcpy`, or any size-dependent operation will corrupt memory.
