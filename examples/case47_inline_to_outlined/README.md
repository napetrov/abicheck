# Case 47: Inline to Outlined Function

**Category:** C++ Symbol | **Verdict:** 🟢 COMPATIBLE

## What breaks
Nothing breaks at the binary level — this is a **compatible extension**.

In v1, `Calculator::add()` is defined `inline` in the header: the compiler emits the
body directly at every call site, and no exported symbol exists in `libv1.so`. In v2,
`add()` is moved out-of-line to `v2.cpp` and its symbol (`_ZN10Calculator3addEii`) is
now exported from `libv2.so`.

Existing binaries compiled against v1 already have the `add()` body inlined — they
never call the symbol, so the new export is invisible to them. New code compiled
against v2 calls the outlined version. Both coexist safely.

The subtle risk is in the **reverse** direction: if v1 headers are accidentally used
with a v2 library that inlines a different body, there is a One-Definition Rule (ODR)
violation. That scenario requires a header downgrade and is not present here.

## Why abidiff catches it
abidiff detects the new exported symbol:

- `FUNC_ADDED`: `Calculator::add(int, int)` appears in v2's `.dynsym`
- Exit code **4** (ABI change detected — addition, not removal)

Because the verdict is `FUNC_ADDED` (not `FUNC_REMOVED`), abicheck classifies this
as **COMPATIBLE**: the addition is a backward-compatible extension.

## Code diff

| v1.hpp | v2.hpp |
|--------|--------|
| `inline int add(int a, int b) { return a + b; }` | `int add(int a, int b);` *(outlined in v2.cpp)* |
| *(no exported symbol)* | `_ZN10Calculator3addEii` exported |

## Real Failure Demo

**Severity: BASELINE** (no breakage expected)

```bash
# Build v1 library + app
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -g -I. app.cpp -L. -lv1 -Wl,-rpath,. -o app
./app
# → add(3,4) = 7  (inline body in app)

# Swap in v2 library (no recompile)
g++ -shared -fPIC -g v2.cpp -o libv1.so
./app
# → add(3,4) = 7  (still uses inlined v1 body — no symbol lookup needed)
# → no crash, no wrong output
```

**Why BASELINE:** The inlined call site in the app binary does not resolve `add`
via the dynamic linker. Swapping the library has no effect on the already-inlined
computation.

## Reproduce manually
```bash
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -shared -fPIC -g v2.cpp -o libv2.so
abidw --out-file v1.xml libv1.so
abidw --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 4 (FUNC_ADDED — compatible)
```

## How to fix
No fix required — this change is compatible. However, be aware of:

1. **ODR risk** — if you later move the inline *back* to the header with a different
   body, consumers that still have the old outlined symbol in their link path may
   call the wrong version. Document the change in release notes.
2. **Debug-info drift** — consumers that relied on the inlined form for debugging
   will now step into the library instead. This is usually desirable.
3. **Consider `[[deprecated]]` + new name** if the move is part of a broader refactor
   to make the function testable or mockable.
