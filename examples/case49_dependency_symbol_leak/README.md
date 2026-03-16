# Case 49: Dependency Symbol Leak (Static Archive Re-export)

**Category:** ELF / Policy | **Verdict:** 🟡 BAD PRACTICE

## What this case is about

When a shared library links a static archive (`.a`) without visibility controls,
the archive's symbols leak into the library's `.dynsym` table. Consumers can
accidentally depend on these internal symbols, coupling the library's ABI to its
dependency's ABI.

**This is NOT a comparison between two ABI versions.**
The bad practice lives in `libv1.so` (the "bad" library) *alone*.
`libv2.so` (the "good" library) shows the correct approach — using
`-fvisibility=hidden` and a version script to export only `core_api`.

## Why leaking dependency symbols is bad practice

- Every `dep_*` symbol becomes part of the library's public ABI contract — even
  though it was never intended for consumers.
- Upgrading the dependency (e.g., switching compression libraries) forces an ABI
  break: the `dep_*` symbols disappear or change signature.
- Consumers that discover and link against `dep_compress` directly will break
  when the library's internal dependency changes.
- It bloats the dynamic symbol table and slows linker resolution.

## What abicheck detects

Running `abicheck dump libv1.so` (without headers) + comparing to `libv2.so`:

- **`VISIBILITY_LEAK`** (BAD PRACTICE / COMPATIBLE): `libv1.so` exports
  dependency symbols (`dep_compress`, `dep_decompress`) that should be hidden.
- **`FUNC_REMOVED_ELF_ONLY`** (COMPATIBLE): dependency symbols disappear in
  `libv2.so`. Classified as compatible because these were never part of the
  intended public API.

**Overall verdict: COMPATIBLE** (the library still works; the bad practice was in v1).

## How to reproduce

```bash
# Build
cd examples/case49_dependency_symbol_leak

# Check libv1.so (bad — leaks dep_* symbols)
nm --dynamic --defined-only libv1.so
# → core_api, dep_compress, dep_decompress  ← leak!

# Check libv2.so (good — only core_api exported)
nm --dynamic --defined-only libv2.so
# → core_api only  ← correct

# Run abicheck (no headers — ELF-only mode)
python3 -m abicheck.cli dump libv1.so -o /tmp/v1.json
python3 -m abicheck.cli dump libv2.so -o /tmp/v2.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
# → COMPATIBLE + VISIBILITY_LEAK warning on libv1.so
```

## How to fix

Use **one or both** of these techniques:

1. **Version script** (`--version-script=exports.map`) to export only your API:
   ```
   { global: core_api; local: *; };
   ```

2. **`--exclude-libs`** linker flag to hide symbols from specific archives:
   ```bash
   gcc -shared -o libcore.so core.o -ldep -Wl,--exclude-libs,libdep.a
   ```

3. **`-fvisibility=hidden`** + explicit `__attribute__((visibility("default")))`
   on your public API functions.

## Real Failure Demo

**Severity: BAD PRACTICE**

**Scenario:** app uses dlopen to verify which symbols are exported.

```bash
# Build dep.a
gcc -fPIC -c dep.c -o dep.o
ar rcs libdep.a dep.o

# Build bad variant (leaks dep_* symbols)
gcc -shared -fPIC -g bad.c libdep.a -o libv1.so

# Build good variant (version script hides dep_*)
gcc -shared -fPIC -g -fvisibility=hidden good.c libdep.a \
    -Wl,--version-script=exports.map -o libv2.so

# Check exports
nm --dynamic --defined-only libv1.so | grep dep_
# → dep_compress, dep_decompress  ← leaked!
nm --dynamic --defined-only libv2.so | grep dep_
# → (empty)  ← correctly hidden

# Run demo app
gcc -g app.c -ldl -o app
./app
# v1.so: core_api     EXPORTED (correct)
# v1.so: dep_compress EXPORTED (leak!)
# v1.so: dep_decompress EXPORTED (leak!)
# v2.so: core_api     EXPORTED (correct)
# v2.so: dep_compress hidden (correct)
```

**Why BAD PRACTICE:** The library works, but its dependency's symbols are part of
the public ABI. Any change to the dependency forces an ABI break for the library.

## Real-world example

GNU ld provides `--exclude-libs` specifically for this: it marks symbols from
selected archives as hidden. Many projects (OpenSSL, systemd) use version scripts
to prevent exactly this kind of leakage.

## References

- [GNU ld `--exclude-libs`](https://sourceware.org/binutils/docs/ld/Options.html)
- [GNU ld version scripts](https://sourceware.org/binutils/docs/ld/VERSION.html)
- [How To Write Shared Libraries — Export Control](https://www.akkadia.org/drepper/dsohowto.pdf)
