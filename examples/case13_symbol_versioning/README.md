# Case 13: Symbol Versioning Script

**Category:** ELF/Linker | **Verdict:** 🔴 BREAKING (versioned→unversioned is a hard symbol lookup failure)

## Why this is BREAKING (versioned → unversioned)
**Direction matters:**
- unversioned → versioned: `ld.so` soft-matches, may continue with a warning
- **versioned → unversioned (this case):** a binary compiled against `foo@@LIBFOO_1.0`
  gets a **hard** `symbol lookup error: undefined symbol: foo@@LIBFOO_1.0` — the dynamic
  linker does NOT map versioned to unversioned. This is a hard loader failure.

Without a version script, symbols have no version tag (`foo` instead of `foo@@LIBFOO_1.0`).
When a consumer is compiled against the versioned library and later runs against the
unversioned variant, `ld.so` emits a warning and typically continues — but this
creates several hard breaking scenarios:

1. **`dlvsym()` failure**: any caller using `dlvsym(handle, "foo", "LIBFOO_1.0")`
   gets `NULL` — a hard runtime error.
2. **Future versioning impossible**: once you ship without a version script, you can
   never add `LIBFOO_2.0` alongside `LIBFOO_1.0` in the same `.so` — the versioning
   infrastructure is gone.
3. **Silent ABI drift**: `ld.so` prints `"no version information available (required
   by /tmp/app)"` to stderr and proceeds — masking incompatibility until a subtle
   runtime failure surfaces later.

Note: the `check_match: Assertion failed!` in `dl-lookup.c` fires under a different
condition (library *has* `DT_VERDEF` but with a mismatched version hash), not when
the version script is simply absent.

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

**Scenario:** app *appears* to run fine after swapping to the unversioned lib — `ld.so`
prints a warning but continues. The break surfaces via `dlvsym()` failure and loss of
future versioning capability.

```bash
# Build good (versioned) and bad (unversioned) .so
gcc -shared -fPIC -g good.c -o libgood.so -Wl,--version-script=libfoo.map
gcc -shared -fPIC -g bad.c  -o libbad.so

# Link app against the versioned lib → DT_VERNEED: LIBFOO_1.0 embedded in binary
cp libgood.so libfoo.so
gcc -g app.c -L. -Wl,-rpath,. -lfoo -o app
./app  # → foo() = 0  bar() = 1

# Swap in unversioned lib → ld.so warning, but basic call still works
cp libbad.so libfoo.so && ./app
# stderr: "no version information available (required by ./app)"
# stdout: foo() = 0  bar() = 1  ← call succeeds, but DT_VERNEED is unsatisfied

# dlvsym() breaks hard:
# dlvsym(handle, "foo", "LIBFOO_1.0") → NULL (version not found in unversioned lib)

# The difference shows up in symbol table
readelf --syms libgood.so | grep foo   # → foo@@LIBFOO_1.0 (versioned)
readelf --syms libbad.so  | grep foo   # → foo           (no version)
```

**Why BREAKING:** Dropping the version script breaks ABI in two ways: (1) any caller
using `dlvsym(handle, "foo", "LIBFOO_1.0")` gets `NULL` — a hard failure; (2) you can
never ship a `LIBFOO_2.0` variant alongside `LIBFOO_1.0` in the same `.so` for backward
compatibility — the versioning mechanism simply doesn't exist. Basic symbol resolution
continues with a warning, but the ABI contract is broken.
