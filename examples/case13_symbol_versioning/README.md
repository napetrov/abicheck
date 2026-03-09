# Case 13: Symbol Versioning Script

**Category:** ELF/Linker | **Verdict:** 🔴 BREAKING

## What breaks
Without a version script, symbols have no version tag (`foo` instead of `foo@@LIBFOO_1.0`).
When a consumer is compiled against the versioned library and later runs against the
unversioned variant, `ld.so` fails with an assertion:

```
no version information available (required by /tmp/app)
Inconsistency detected by ld.so: dl-lookup.c: check_match: Assertion failed!
```

This is a hard runtime crash (exit 127) — not just a future-proofing concern.

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

## Real Failure Demo

**Severity: BREAKING**

**Scenario:** app runs fine against both good.so and bad.so at runtime. The issue is future-proofing.

```bash
# Build good (versioned) and bad (unversioned) .so
gcc -shared -fPIC -g good.c -o libgood.so -Wl,--version-script=libfoo.map
gcc -shared -fPIC -g bad.c  -o libbad.so

# Runtime works either way — must copy to libfoo.so before linking
cp libgood.so libfoo.so
gcc -g app.c -L. -Wl,-rpath,. -lfoo -o app
./app  # → foo() = 0  bar() = 1

cp libbad.so libfoo.so && ./app  # → foo() = 0  bar() = 1

# The difference shows up in symbol table
readelf --syms libgood.so | grep foo   # → foo@@LIBFOO_1.0 (versioned)
readelf --syms libbad.so  | grep foo   # → foo           (no version)
```

**Why BREAKING:** An app linked against the versioned library embeds `DT_VERNEED: LIBFOO_1.0` in its ELF. When swapped to the unversioned lib at runtime, `ld.so` cannot satisfy the version requirement and aborts with an assertion error.
you can never ship a `LIBFOO_2.0` variant alongside `LIBFOO_1.0` in the same `.so` for
backward compatibility — the versioning mechanism simply doesn't exist.
