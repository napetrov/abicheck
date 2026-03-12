# Case 45: Multi-Dimensional Array Element Type Change

**Category:** Struct Layout | **Verdict:** 🔴 BREAKING

## What breaks
`Matrix.data` changes from `float[4][4]` to `double[4][4]`. The element type doubles
in size (4 → 8 bytes), so the array grows from 64 bytes to 128 bytes. Because `data`
is the first member of `Matrix`, every subsequent field (`rows`, `cols`) shifts by
64 bytes. Any caller that accesses `rows`, `cols`, or individual array elements
through a stale v1-compiled binary reads completely wrong memory.

Additionally, the return type of `matrix_get()` changes from `float` to `double`,
which alters the calling convention on some architectures (different floating-point
registers).

## Why abidiff catches it
abidiff detects the element-type change within the multi-dimensional array sub-ranges:

- `TYPE_SIZE_CHANGED` on `Matrix` (72 → 136 bytes)
- `TYPE_FIELD_TYPE_CHANGED` on `data` (element type `float` → `double`)
- `TYPE_FIELD_OFFSET_CHANGED` on `rows` and `cols` (offset shifts by 64 bytes)
- `FUNC_RETURN_CHANGED` on `matrix_get` (`float` → `double`)
- Exit code **4** (ABI change detected)

## Code diff

| v1.h | v2.h |
|------|------|
| `float data[ROWS][COLS];` (64 bytes) | `double data[ROWS][COLS];` (128 bytes) |
| `float matrix_get(const Matrix *m, int r, int c);` | `double matrix_get(const Matrix *m, int r, int c);` |
| `sizeof(Matrix) == 72` | `sizeof(Matrix) == 136` |

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile caller against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 library + caller
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g -I. app.c -L. -lv1 -Wl,-rpath,. -o app
./app
# → m.rows = 4, m.cols = 4, get(0,0) = 1.5  (correct)

# Swap in v2 library (no recompile)
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# → m.rows = <garbage>, get(0,0) = NaN or wrong value
# → caller passes float-sized buffer; lib reads as double, crosses field boundaries
```

**Why CRITICAL:** The caller allocates `Matrix` with `sizeof(Matrix)` baked in at
compile time (72 bytes). The library treats the pointer as pointing to a 136-byte
struct. Reading `rows` reads 64 bytes past the expected array end, hitting either
uninitialised memory or another variable entirely.

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
1. **Do not expose array element types in public structs.** Use an opaque handle or
   pointer to an incomplete type; resize internally.
2. **Template / generic matrix** — if the precision must be configurable, use a
   separate type (`FloatMatrix` / `DoubleMatrix`) and never change an existing one.
3. **Versioned struct** — introduce `Matrix_v2` with the new layout; keep `Matrix`
   (v1) for backward compatibility, provide conversion helpers.
4. **SONAME bump** — if the change is unavoidable, bump the major version and require
   consumer recompilation.
