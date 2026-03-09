
## Real Failure Demo

**Severity: BAD PRACTICE**

**Scenario:** build `app` against bad.so (no SONAME) vs good.so (with SONAME).

```bash
# Build both variants
gcc -shared -fPIC -g bad.c  -o libbad.so
gcc -shared -fPIC -g good.c -o libgood.so -Wl,-soname,libfoo.so.1

# Check SONAME presence
readelf -d libgood.so | grep SONAME   # → (SONAME) Library soname: [libfoo.so.1]
readelf -d libbad.so  | grep SONAME   # → (empty — no SONAME)

# Runtime: works either way
gcc -g app.c -L. -Wl,-rpath,. -lfoo -o app   # link against libbad.so renamed to libfoo.so
./app
# → foo() = 0

# The problem: without SONAME, ldconfig can't create libfoo.so.1 symlink
sudo ldconfig
ldconfig -p | grep libfoo.so.1   # → missing for bad.so; present for good.so
```

**Why BAD PRACTICE:** The runtime works, but without a SONAME the dynamic linker
embeds the bare filename in DT_NEEDED. If you later ship `libfoo.so.1`, existing
binaries won't find it and packaging tools (ldconfig, dpkg) can't manage the symlink tree.
