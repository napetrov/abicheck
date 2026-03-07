# Case 06: Symbol Visibility Leak

**Category:** Visibility | **Verdict:** 🟡 INFORMATIONAL

## What breaks
Every symbol compiled without `-fvisibility=hidden` becomes part of the public ABI
unintentionally. Any refactor of internal helpers becomes a potential ABI break.
Bloated symbol tables also slow dynamic linking startup.

## Why the check catches it
`nm --dynamic --defined-only` on the "bad" library shows internal symbols like
`internal_helper` and `another_impl`. The "good" library (compiled with
`-fvisibility=hidden` + `__attribute__((visibility("default")))` on public API)
exports only `public_api`.

## Build comparison

```
# good: only public_api exported
gcc -shared -fPIC -fvisibility=hidden good.c -o libgood.so

# bad: everything exported
gcc -shared -fPIC bad.c -o libbad.so
```

## Reproduce manually
```bash
gcc -shared -fPIC -fvisibility=hidden good.c -o libgood.so
gcc -shared -fPIC bad.c  -o libbad.so
nm --dynamic --defined-only libgood.so  # only public_api
nm --dynamic --defined-only libbad.so   # public_api + internal_helper + another_impl
```

## How to fix
Add `-fvisibility=hidden` to the build flags and annotate every intended public
function with `__attribute__((visibility("default")))`. Use a `FOO_EXPORT` macro
to keep it readable.

## Real-world example
Qt and most large C++ frameworks gate their public API with `Q_DECL_EXPORT` macros
precisely to avoid this. GCC's `-fvisibility=hidden` is their standard practice
since Qt 4.
