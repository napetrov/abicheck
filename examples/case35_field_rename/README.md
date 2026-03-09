# Case 35 -- Field Rename

**abicheck verdict: SOURCE_BREAK**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `struct Point { int x; int y; };` |
| v2 | `struct Point { int col; int row; };` |

## Why this is NOT a binary ABI break

Renaming struct fields does not change the binary layout. The fields `x`/`col`
are at offset 0 and `y`/`row` are at offset 4 in both versions. Field names
are not encoded in the compiled binary -- they are resolved to offsets at
compile time. A binary compiled against v1 will continue to work correctly
with v2's shared library because `make_point()` returns the same struct layout.

However, source code referencing `p.x` or `p.y` will fail to compile against
v2's header, making this a source-level break.

## Code diff

```diff
 struct Point {
-    int x;      /* offset 0 */
-    int y;      /* offset 4 */
+    int col;    /* offset 0 -- was x */
+    int row;    /* offset 4 -- was y */
 };
```

## Real Failure Demo

**Severity: SOURCE_BREAK (binary compatible)**

```bash
# Build v1 lib + app
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g app.c -I. -L. -lv1 -Wl,-rpath,. -o app
./app
# -> p.x = 10
# -> p.y = 20

# Swap to v2 .so (do NOT recompile app)
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# -> p.x = 10       <-- still correct! binary layout unchanged
# -> p.y = 20       <-- still correct!

# But recompiling against v2 header FAILS:
sed 's/#include "v1.h"/#include "v2.h"/' app.c > /tmp/app_v2_test.c
gcc -g /tmp/app_v2_test.c -I. -L. -lv1 -Wl,-rpath,. -o app
# -> error: 'struct Point' has no member named 'x'
rm -f /tmp/app_v2_test.c
```

**Why SOURCE_BREAK:** The struct layout is bit-for-bit identical between v1 and v2.
Only the field names changed, which are a compile-time concept. Existing binaries
are fully compatible.
