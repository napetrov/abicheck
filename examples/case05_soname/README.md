# Case 05: Missing SONAME

**Category:** ELF/Linker | **Verdict:** 🟡 BAD PRACTICE

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

## Real Failure Demo

**Severity: BAD PRACTICE**

**Scenario:** build `app` against bad.so (no SONAME) vs good.so (with SONAME). Runtime works either way — the issue is packaging and future versioning.

```bash
# Build both variants
gcc -shared -fPIC -g bad.c  -o libbad.so
gcc -shared -fPIC -g good.c -o libgood.so -Wl,-soname,libfoo.so.1

# Check SONAME presence
readelf -d libgood.so | grep SONAME   # → (SONAME) Library soname: [libfoo.so.1]
readelf -d libbad.so  | grep SONAME   # → (empty — no SONAME)

# Build app (requires libfoo.so to exist at link time)
cp libbad.so libfoo.so
gcc -g app.c -L. -Wl,-rpath,. -lfoo -o app
./app
# → foo() = 0   (works at runtime)

# The problem: without SONAME, ldconfig can't create versioned symlink
sudo ldconfig
ldconfig -p | grep libfoo.so.1   # → missing for bad.so; present for good.so
```

**Why BAD PRACTICE:** The runtime works, but without a SONAME the dynamic linker
embeds the bare filename in DT_NEEDED. If you later ship `libfoo.so.1`, existing
binaries won't find it and packaging tools (ldconfig, dpkg) can't manage the symlink tree.
