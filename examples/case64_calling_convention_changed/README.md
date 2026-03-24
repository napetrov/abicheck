# Case 64: Calling Convention Changed

**Category:** Function ABI | **Verdict:** BREAKING

## What breaks

The functions `vector_dot` and `vector_scale` change from the default System V
AMD64 calling convention to `__attribute__((regcall))`. This changes which CPU
registers carry function parameters and return values. A caller compiled against
v1 passes arguments in the default registers (`rdi`, `rsi`, `rdx`, `xmm0`...),
but the v2 function reads from the regcall register set — getting garbage or
stale values.

## Why this matters

Calling conventions define the **fundamental contract** between caller and callee:
- Which registers hold which parameters
- How the return value is passed back
- Who saves/restores which registers (caller-saved vs callee-saved)
- Stack alignment requirements

When this contract is violated, the function operates on completely wrong data.
The result is either garbage output, a segfault (if a pointer parameter is wrong),
or silent data corruption.

This is particularly dangerous in math/compute libraries where:
- Performance-sensitive code may switch to vectorcall/regcall for SIMD register usage
- The library "works fine" when rebuilt from source — the bug only manifests with
  pre-compiled consumers

## Code diff

```c
/* v1: default calling convention */
double vector_dot(const double *a, const double *b, int len);

/* v2: regcall convention — different register assignment */
__attribute__((regcall))
double vector_dot(const double *a, const double *b, int len);
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build old library + app
gcc -shared -fPIC -g v1.c -o libfoo.so
gcc -g app.c -L. -lfoo -Wl,-rpath,. -o app -lm
./app
# → dot product = 32.0 (expected 32.0)
# → scaled = {2.0, 4.0, 6.0} (expected {2.0, 4.0, 6.0})

# Swap in new library (no recompile)
# Note: regcall requires clang; gcc may not support it
clang -shared -fPIC -g v2.c -o libfoo.so
./app
# → dot product = 0.0 (expected 32.0)
# → WRONG RESULT: calling convention mismatch
```

**Why CRITICAL:** The v2 function expects parameters in regcall registers but
receives them in System V registers. The function reads uninitialized register
values, producing wrong results. With pointer arguments, this could cause a
segfault instead.

## How to fix

Never change the calling convention of an exported function. If a new convention
is needed:

1. **Add a new symbol**: `vector_dot_fast()` with the new convention
2. **Use a wrapper**: keep the old entry point as a thin wrapper that forwards to
   the optimized implementation
3. **Version the API**: provide `libmath_v2.so` with the new convention and a
   migration guide

## Real-world example

The Windows ecosystem has dealt with this extensively: `__stdcall` vs `__cdecl`
vs `__fastcall` vs `__vectorcall` have caused countless DLL compatibility issues.
The Win32 API froze on `__stdcall` specifically to prevent this class of break.

Intel's Math Kernel Library (MKL) uses `__cdecl` for its public API but internally
uses `__vectorcall` for SIMD-heavy routines — the public entry points are thin
wrappers that preserve the calling convention contract.

## abicheck detection

abicheck detects this as `calling_convention_changed` (BREAKING) by comparing
DWARF `DW_AT_calling_convention` attributes between the two binary versions.

## References

- [System V AMD64 ABI — Register usage](https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf)
- [Intel regcall convention](https://www.intel.com/content/www/us/en/docs/cpp-compiler/developer-guide-reference/current/regcall.html)
- [DWARF5 §5.7.1 — DW_AT_calling_convention](https://dwarfstd.org/doc/DWARF5.pdf)
