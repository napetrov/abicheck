# Case 05: Missing SONAME

**Category:** ELF/Linker | **Verdict:** 🟡 INFORMATIONAL

## What breaks
Without a SONAME, the dynamic linker records the bare filename (`libfoo.so`) in
`DT_NEEDED` entries of every consumer. If you later ship `libfoo.so.1`, existing
binaries won't find it. SONAME is how Linux implements library versioning.

## Why the check catches it
`readelf -d` on a well-built library shows `(SONAME) Library soname: [libfoo.so.1]`.
Its absence means the library was linked without `-Wl,-soname`.

## Build comparison

| good.c (with SONAME) | bad.c (without) |
|---|---|
| `gcc -shared -fPIC good.c -o libfoo.so -Wl,-soname,libfoo.so.1` | `gcc -shared -fPIC bad.c -o libfoo.so` |
| `readelf -d` → `(SONAME) libfoo.so.1` | `readelf -d` → *(no SONAME entry)* |

## Reproduce manually
```bash
gcc -shared -fPIC good.c -o libgood.so -Wl,-soname,libfoo.so.1
gcc -shared -fPIC bad.c  -o libbad.so
readelf -d libgood.so | grep SONAME   # → present
readelf -d libbad.so  | grep SONAME   # → empty
```

## How to fix
Always pass `-Wl,-soname,libname.so.MAJOR` when building a shared library intended
for system installation.

## Real-world example
Many in-tree/vendored libraries built with simple `Makefile`s omit SONAME. Debian
packaging policy enforces SONAME presence and will reject packages without it.
