# Case 59: Function Became Inline (outlined → inline)

**Category:** Symbol API | **Verdict:** BREAKING (API_BREAK)

## What this case is about

v1 exports `fast_abs` and `fast_max` as regular outlined functions in the
shared library. v2 moves them to the header as `static inline` — the symbols
disappear from `.dynsym`.

This is the **inverse of case47** (inline_to_outlined), which is compatible.
Moving a function from outlined to inline is **breaking** because existing
binaries depend on the symbol being in the library.

## What breaks at binary level

- **Symbols removed**: `fast_abs` and `fast_max` are no longer in `.dynsym`.
- **Dynamic linker fails**: Existing binaries that reference these symbols
  get `undefined symbol` errors at load time.
- **Source compatibility preserved**: New compilations with the v2 header work
  fine (the inline definition is available), but old binaries break.

## What abicheck detects

- **`FUNC_REMOVED`**: Both function symbols are absent from v2's export table.
  From the binary perspective, this is indistinguishable from deletion.

**Overall verdict: BREAKING**

## How to reproduce

```bash
gcc -shared -fPIC -g bad.c  -o libbad.so
gcc -shared -fPIC -g good.c -o libgood.so

nm -D libbad.so  | grep fast_  # → T fast_abs, T fast_max
nm -D libgood.so | grep fast_  # → (nothing — inlined away)

# Link app against v1
gcc -g app.c -L. libbad.so -Wl,-rpath,. -o app
./app  # works

# Swap to v2
cp libgood.so libbad.so
./app
# → error: undefined symbol: fast_abs
```

## How to fix

Keep an outlined fallback alongside the inline version:

```c
/* header */
static inline int fast_abs(int x) { return x < 0 ? -x : x; }

/* .c file — provide an exported symbol for backward compat */
extern inline int fast_abs(int x);
```

Or use a `__attribute__((weak))` symbol.

## References

- [C99 inline semantics](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)
