# Case 46: Pointer Chain Type Change

**Category:** Function Signature | **Verdict:** 🔴 BREAKING

## What breaks
`get_matrix()` returns `int **` in v1 and `long **` in v2. The ultimate pointee type
changes from `int` (4 bytes) to `long` (8 bytes on 64-bit). Callers that dereference
the double-indirect pointer chain and read individual elements interpret each 8-byte
`long` as a 4-byte `int`, reading only half the value and mistaking the next element's
bytes for a separate cell.

`set_cell()` and `sum_row()` also change their pointer-chain parameter types and return
types along the same `int` → `long` axis.

## Why abidiff catches it
abidiff walks the full pointer chain in the DWARF/castxml type graph and detects the
ultimate pointee-type change:

- `FUNC_RETURN_CHANGED` on `get_matrix` (`int **` → `long **`)
- `PARAM_TYPE_CHANGED` on `set_cell` and `sum_row` (pointer params `int *const *` → `long *const *`)
- `FUNC_RETURN_CHANGED` on `sum_row` (`int` → `long`)
- Exit code **4** (ABI change detected)

## Code diff

| v1.h | v2.h |
|------|------|
| `int **get_matrix(void);` | `long **get_matrix(void);` |
| `void set_cell(int *const *matrix, int row, int col, int val);` | `void set_cell(long *const *matrix, int row, int col, long val);` |
| `int sum_row(int *const *matrix, int row, int cols);` | `long sum_row(long *const *matrix, int row, int cols);` |

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile caller against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 library + caller
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g -I. app.c -L. -lv1 -Wl,-rpath,. -o app
./app
# → sum_row(0) = 6  (correct for int row [1,2,3])

# Swap in v2 library (no recompile)
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# → sum_row(0) = 0 or garbage: int-sized reads over long-sized array elements
# → or: SIGSEGV if pointer alignment breaks
```

**Why CRITICAL:** The caller's dereferencing code treats each element as `sizeof(int)`
(4 bytes) while the library writes them as `sizeof(long)` (8 bytes). Every second read
lands in padding or the next element, producing wrong sums and potentially corrupting
memory if `set_cell()` writes with the wrong stride.

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
1. **Use fixed-width types** in public APIs (`int32_t`, `int64_t` from `<stdint.h>`)
   and never change them — platform-size types like `long` vary across ABIs.
2. **Opaque handle / stride parameter** — pass an opaque handle plus an explicit
   element-size argument so the pointee type is decoupled from the ABI.
3. **New symbol name** — introduce `get_matrix_l()` returning `long **`; keep
   `get_matrix()` returning `int **` for backward compatibility.
4. **SONAME bump** — if the signature must change, bump the major version and force
   recompilation of all consumers.
