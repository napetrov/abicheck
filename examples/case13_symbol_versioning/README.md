# Case 13: Symbol Versioning Script

**Category:** ELF/Linker | **Verdict:** 🟡 INFORMATIONAL

## What breaks
Without a version script, symbols have no version tag. If you later need to ship a
`LIBFOO_2.0` variant of a symbol (for ABI fix while keeping backward compat), you
have no mechanism to do so — all consumers already link against the unversioned symbol
and there's no way to differentiate.

## Why the check catches it
`readelf --syms` on the "good" library shows `foo@@LIBFOO_1.0` — the `@@` denotes the
default (current) version. The "bad" library shows bare `foo` with no version suffix.

## Build comparison

| good.c + libfoo.map | bad.c (no map) |
|---|---|
| `gcc ... -Wl,--version-script=libfoo.map` | `gcc -shared -fPIC bad.c -o libbad.so` |
| `readelf --syms` → `foo@@LIBFOO_1.0` | `readelf --syms` → `foo` |

## Reproduce manually
```bash
# good
gcc -shared -fPIC good.c -o libgood.so -Wl,--version-script=libfoo.map
readelf --syms libgood.so | grep foo   # → foo@@LIBFOO_1.0

# bad
gcc -shared -fPIC bad.c -o libbad.so
readelf --syms libbad.so | grep foo    # → foo (no version)
```

`libfoo.map` content:
```
LIBFOO_1.0 {
  global: foo; bar;
  local: *;
};
```

## How to fix
Always supply a linker version script for public libraries. This enables future
`LIBFOO_2.0` blocks for compatible evolution and precise control over the public
symbol set.

## Real-world example
glibc uses symbol versioning extensively — `GLIBC_2.5`, `GLIBC_2.17`, etc. — allowing
the same `libc.so.6` to serve binaries built against many different historical versions
simultaneously.
