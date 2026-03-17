# Platform Support

abicheck runs on **Linux, macOS, and Windows** and can analyze binaries from any of these platforms.
However, the depth of analysis depends on the **host platform** and whether headers are available.

---

## Quick Reference: What Works Where

### Scanning Linux ELF binaries

| Host OS | Symbol diff | Type/param diff | Requires |
|---------|------------|----------------|---------|
| Linux ✅ | ✅ Full | ✅ Full | `castxml`, `g++`/`gcc` |
| macOS | ✅ Yes | ❌ No | — |
| Windows | ✅ Yes | ❌ No | — |

**Best results:** run on Linux with headers provided.

### Scanning Windows PE (DLL) binaries

| Host OS | Symbol diff | Type/param diff | Requires |
|---------|------------|----------------|---------|
| Linux | ✅ Yes | ❌ No | `pefile` |
| macOS | ✅ Yes | ❌ No | `pefile` |
| Windows | ✅ Yes | ✅ Yes | `castxml` + `cl.exe` |

### Scanning macOS Mach-O (dylib) binaries

| Host OS | Symbol diff | Type/param diff | Requires |
|---------|------------|----------------|---------|
| Linux | ✅ Yes | ❌ No | `macholib` |
| macOS | ✅ Yes | ✅ Yes | `castxml` (Xcode clang) |
| Windows | ✅ Yes | ❌ No | `macholib` |

---

## What "Symbols Only" Mode Means

When scanning a binary **without headers**, or scanning a non-native binary cross-platform,
abicheck operates in **symbol-table mode**:

✅ **Detected:**
- Function added / removed (`func_added`, `func_removed`)
- SONAME changed (`soname_changed`)
- Symbol visibility changed (`symbol_visibility_changed`)
- Variable added / removed

❌ **Not detected** (requires type information from headers + castxml):
- Parameter type changes (`func_params_changed`)
- Return type changes (`func_return_type_changed`)
- Struct/class layout changes (`type_size_changed`, `type_field_*`)
- vtable changes (`type_vtable_changed`)
- Inline/noexcept changes

**Recommendation:** for complete ABI analysis, always provide `-H <header_dir>` and run on the
native platform (Linux for ELF, macOS for Mach-O, Windows for PE).

---

## Cross-Platform Examples

### Scan a Windows DLL from Linux

```bash
# Symbol-level diff (works cross-platform)
abicheck compare mylib_v1.dll mylib_v2.dll

# With headers (only useful if castxml+cl.exe is available)
abicheck compare mylib_v1.dll mylib_v2.dll \
  -H include/
```

**What you get:** `func_removed`, `func_added`, ordinal changes.
**What you miss:** parameter type changes, struct layout changes.

### Scan a macOS dylib from Linux

```bash
abicheck compare libmylib.1.dylib libmylib.2.dylib
```

**What you get:** exported symbol diff.
**What you miss:** type-level analysis (no DWARF walk cross-platform today).

### Scan a Linux .so from macOS

```bash
abicheck compare libmylib.so.1 libmylib.so.2
```

ELF parsing is pure Python — works on macOS. DWARF walk also works.
Full type analysis requires `castxml` and headers available on the host.

---

## GitHub Actions: Multi-Platform CI

To get full analysis on each platform:

```yaml
jobs:
  abi-check:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - name: Install abicheck (source)
        run: pip install -e .
      - name: Install castxml (Linux/macOS only)
        if: runner.os != 'Windows'
        run: |
          # sudo apt-get install -y castxml   # Ubuntu
          # brew install castxml              # macOS
      - name: ABI check
        run: |
          abicheck compare -lib mylib \
            -old old/libmylib.so -new new/libmylib.so \
            -H include/
```

---

## Known Limitations by Platform

### Windows host
- `castxml` with `cl.exe` backend is **untested in CI** — may work but is not validated
- MSVC vtable layout differs from Itanium ABI; vtable diff results may be inaccurate
- `__stdcall`/`__cdecl` calling convention differences not tracked
- Tracked: abicc upstream issues #9, #50, #56, #121

### macOS host
- ARM64 Apple AAPCS differs from Itanium for small structs (≤16 bytes passed in registers)
- `install_name` (macOS SONAME equivalent) — tracked but not surfaced as `soname_changed` yet
- Two-level namespace (`LC_LOAD_DYLIB`) not fully analyzed
- Tracked: abicc upstream issues #116, #119

### All platforms (symbols-only mode)
- `int → long` parameter change: mangled name changes → detected as `func_removed + func_added`
  (not `func_params_changed`) when headers are absent
- Template inner-type changes (`std::vector<T>` with changed `T`) — not detected (tracked: #38)

---

## Dependency Summary

| Feature | Required tools | pip / system install | conda-forge install |
|---------|----------------|----------------------|---------------------|
| ELF analysis | `pyelftools` | `pip install -e .` | `conda install -c conda-forge abicheck` |
| PE analysis | `pefile` | `pip install -e .` | `conda install -c conda-forge abicheck` |
| Mach-O analysis | `macholib` | `pip install -e .` | `conda install -c conda-forge abicheck` |
| Type/param analysis (Linux) | `castxml` + C/C++ compiler | `pip install -e .` + `apt/yum` (`castxml`, `gcc/g++`) | `conda install -c conda-forge abicheck` |
| Type/param analysis (macOS) | `castxml` + Apple toolchain | `pip install -e .` + `brew install castxml` (+ Xcode CLT) | `conda install -c conda-forge abicheck` |
| Type/param analysis (Windows) | `castxml` + `cl.exe` | `pip install -e .` + Visual Studio Build Tools + castxml | `conda install -c conda-forge abicheck` |

For conda-based workflows, install only `abicheck` from conda-forge.
Recipe dependencies pull required analysis tooling automatically.
