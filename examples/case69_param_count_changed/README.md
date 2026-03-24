# Case 69: Parameter Count Changed

**Category:** Function ABI | **Verdict:** BREAKING

## What breaks

A third parameter `double z` is added to `transform()`. Old binaries compiled
against v1 push only two `double` arguments (in `%xmm0` and `%xmm1` on x86-64
System V). v2 reads a third argument from `%xmm2`, which was never set by the
caller — it contains whatever garbage was left in that register.

This is different from case02 (parameter **type** change) because here the
parameter **count** changes, meaning the callee reads an argument that the
caller never provided at all.

## Why abicheck catches it

Header comparison detects that `transform` changed from 2 parameters to 3
parameters (`func_params_changed`). This is flagged as BREAKING because old
binaries will silently read an uninitialized register value.

## Code diff

| v1.h | v2.h |
|------|------|
| `double transform(double x, double y)` | `double transform(double x, double y, double z)` |

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build old library + app
gcc -shared -fPIC -g v1.c -o libfoo.so
gcc -g app.c -L. -lfoo -Wl,-rpath,. -o app
./app
# -> transform(3.0, 4.0) = 10.0
# -> Expected: 10.0

# Swap in new library (no recompile)
gcc -shared -fPIC -g v2.c -o libfoo.so
./app
# -> transform(3.0, 4.0) = <garbage> (z reads uninitialized xmm2 register)
```

**Why CRITICAL:** v2 reads a third `double` from `%xmm2` that the old caller
never set. The result silently includes a garbage value — no crash, no warning,
just wrong output.

## How to fix

Add a new function with the extended signature and keep the old one:

```c
/* Backward-compatible evolution */
double transform(double x, double y);                /* keep for old callers */
double transform_3d(double x, double y, double z);   /* new interface */
```

Or use a struct/options pattern for extensible parameter lists.

## Real-world example

OpenSSL has added parameters to internal functions between versions, requiring
careful symbol versioning to avoid breaking existing binaries. BLAS/LAPACK
routines occasionally gain workspace parameters in new versions.

## References

- [System V AMD64 ABI: register assignment for floating-point args](https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf)
- [KDE Binary Compatibility Issues](https://community.kde.org/Policies/Binary_Compatibility_Issues_With_C%2B%2B)
