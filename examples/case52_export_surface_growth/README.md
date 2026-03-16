# Case 52: Export Surface Growth (Uncontrolled New Exports)

**Category:** ELF / Policy | **Verdict:** 🟢 COMPATIBLE (🟡 bad practice)

## What this case is about

Between v1 and v2, the library gains several new exported symbols that are
clearly internal (`_process_buffer_internal`, `_validate_input_impl`,
`_cache_lookup_detail`). These symbols were not added to the public header
and are not intended for consumers — they leaked because the library was
built without `-fvisibility=hidden`.

This is a **compatible change** (new symbols are additions), but it is
**bad practice** because:

1. Each leaked symbol becomes part of the public ABI contract.
2. Future refactoring of these internals risks ABI breakage.
3. The export surface grows unboundedly with each release.

## Why export surface growth is bad practice

- **ABI surface creep**: every internal function that gets exported must be
  maintained forever (or its removal is a breaking change).
- **Consumer accidents**: downstream code may discover and link against
  `_process_buffer_internal` — then break when it's renamed or removed.
- **Symbol resolution cost**: more exports = more `.dynsym` scanning at
  dynamic linker startup.
- **Security surface**: internal functions may not have the same input
  validation as public API, creating attack surface if called directly.

## What abicheck detects

- **`FUNC_ADDED`** (COMPATIBLE): new symbols appear in v2 that were not in v1.
- **`VISIBILITY_LEAK`** (BAD PRACTICE): if internal-looking patterns are detected
  in the export table, abicheck flags them as accidental ABI surface.

**Overall verdict: COMPATIBLE** (additions are not breaking).

## How to reproduce

```bash
# Build
cd examples/case52_export_surface_growth

# Check v1 (clean — only public_api)
nm --dynamic --defined-only libv1.so
# → public_api

# Check v2 (bloated — internal symbols leaked)
nm --dynamic --defined-only libv2.so
# → public_api, _process_buffer_internal, _validate_input_impl, _cache_lookup_detail

# Run abicheck
python3 -m abicheck.cli dump libv1.so -o /tmp/v1.json
python3 -m abicheck.cli dump libv2.so -o /tmp/v2.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
# → COMPATIBLE + FUNC_ADDED for internal symbols
```

## How to fix

1. **Build with `-fvisibility=hidden`** and mark only public API functions:
   ```c
   #define MY_EXPORT __attribute__((visibility("default")))
   MY_EXPORT int public_api(int x);
   // internal functions stay hidden automatically
   ```

2. **Use a version script** to whitelist exports:
   ```
   { global: public_api; local: *; };
   ```

3. **CI rule**: fail if new exports appear that are not in the public header
   allowlist.

## Real Failure Demo

**Severity: BAD PRACTICE**

```bash
# Build both variants
gcc -shared -fPIC -g good.c -o libv1.so
gcc -shared -fPIC -g bad.c  -o libv2.so

# Compare export surfaces
echo "=== v1 exports ==="
nm --dynamic --defined-only libv1.so | grep ' T '
# → public_api

echo "=== v2 exports ==="
nm --dynamic --defined-only libv2.so | grep ' T '
# → public_api, _process_buffer_internal, _validate_input_impl, _cache_lookup_detail

# Run demo app
gcc -g app.c -ldl -o app
./app
# v1: only public_api exported
# v2: all internal functions also exported (leak!)
```

**Why BAD PRACTICE:** The library works, but its internal implementation
details are now part of the public ABI. Any refactoring of these internals
in a future release will appear as an ABI break.

## Real-world example

Qt, GCC libstdc++, LLVM, and most large C/C++ projects enforce export
control via visibility macros precisely to prevent this kind of ABI surface
creep. Without it, every internal function becomes a compatibility obligation.

## References

- [GCC visibility](https://gcc.gnu.org/wiki/Visibility)
- [How To Write Shared Libraries — Export Control](https://www.akkadia.org/drepper/dsohowto.pdf)
