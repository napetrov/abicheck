# Case 53: Symbol Versioning Missing

**Category:** ELF / Policy | **Verdict:** 🟢 COMPATIBLE

## What this case is about

Both libraries export the same symbols with identical signatures and behavior.
The difference is that v1 has **no symbol versioning** while v2 assigns all
symbols to a `MYLIB_1.0` version node using `.symver` directives and a version
script.

This is a **compatible change** — existing binaries work with either version.
But shipping without symbol versioning is a missed opportunity that makes future
ABI evolution harder.

## Why missing symbol versioning is bad practice

- **Burns a bridge**: without versioning, you cannot introduce incompatible
  changes to individual symbols while maintaining backward compatibility.
  Your only option for breaking changes is a full SONAME bump, which forces
  all consumers to rebuild.
- **No `dlvsym` support**: consumers that use `dlvsym()` to request a specific
  symbol version will fail if no versions exist.
- **Deployment risk**: if you later add versioning, binaries linked against
  the unversioned library may not correctly bind to the versioned symbols
  (depending on linker behavior with `@` vs `@@`).
- **Ecosystem expectations**: glibc, libstdc++, and many system libraries
  use symbol versioning extensively. Long-lived libraries benefit from
  establishing a versioning baseline early.

## What abicheck detects

- **`SYMBOL_VERSION_DEFINED_ADDED`** (COMPATIBLE): v2 introduces version
  definitions (`MYLIB_1.0`) that did not exist in v1.

**Overall verdict: COMPATIBLE** (same symbols; versioning is additive metadata).

## How to reproduce

```bash
# Build both variants
gcc -shared -fPIC -g bad.c -o libv1.so
gcc -shared -fPIC -g good.c -o libv2.so \
    -Wl,--version-script=version.map

# Check versioning
readelf --dyn-syms libv1.so | grep api_
# → api_init, api_process, api_cleanup  (no version tags)

readelf --dyn-syms libv2.so | grep api_
# → api_init@@MYLIB_1.0, api_process@@MYLIB_1.0, api_cleanup@@MYLIB_1.0

# Verify version definitions
readelf -V libv2.so
# → Version definition section: MYLIB_1.0

# Run abicheck
python3 -m abicheck.cli dump libv1.so -o /tmp/v1.json
python3 -m abicheck.cli dump libv2.so -o /tmp/v2.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
# → COMPATIBLE + SYMBOL_VERSION_DEFINED_ADDED
```

## How to fix

1. **Create a version script** (`version.map`):
   ```
   MYLIB_1.0 {
       global:
           api_init;
           api_process;
           api_cleanup;
       local:
           *;
   };
   ```

2. **Add `.symver` directives** in your source (or rely on the version script
   wildcard matching):
   ```c
   __asm__(".symver api_init,api_init@@MYLIB_1.0");
   ```

3. **Link with the version script**:
   ```bash
   gcc -shared -o libmylib.so mylib.o -Wl,--version-script=version.map
   ```

4. **Future evolution**: add new version nodes as needed:
   ```
   MYLIB_1.1 {
       global:
           api_new_feature;
   } MYLIB_1.0;
   ```

## Real Failure Demo

**Severity: INFORMATIONAL**

```bash
# Build both variants
gcc -shared -fPIC -g bad.c -o libv1.so
gcc -shared -fPIC -g good.c -o libv2.so \
    -Wl,--version-script=version.map

# Build app against unversioned lib
gcc -g app.c -L. -Wl,-rpath,. -lv1 -o app
./app
# → api_process(21) = 42  (works)

# Swap in versioned lib — still works
cp libv2.so libv1.so
./app
# → api_process(21) = 42  (still works)

# But: readelf shows the difference
readelf -V libv1.so 2>/dev/null || echo "(no version info)"
readelf -V libv2.so
# → MYLIB_1.0 version node present
```

**Why INFORMATIONAL:** Everything works today. The concern is long-term:
without a versioning baseline, future incompatible changes to individual
symbols require a full SONAME bump instead of a targeted version node addition.

## Real-world example

glibc uses symbol versioning extensively (`GLIBC_2.0`, `GLIBC_2.17`, etc.)
to maintain decades of backward compatibility while evolving individual
functions. The versioning mechanism allows old binaries to bind to old
implementations while new binaries get improved versions.

## References

- [GNU ld version scripts](https://sourceware.org/binutils/docs/ld/VERSION.html)
- [How To Write Shared Libraries — Symbol Versioning](https://www.akkadia.org/drepper/dsohowto.pdf)
- [Linux Standard Base — ELF Symbol Versioning](https://refspecs.linuxbase.org/LSB_5.0.0/LSB-Core-generic/LSB-Core-generic/symversion.html)
