# New Features Guide: Build Context, Debug Resolution, and Baseline Registry

This guide explains the three new capabilities added to abicheck and how they
improve your ABI checking workflow.

---

## 1. Build-Context Capture (`compile_commands.json`)

### The problem it solves

Previously, when checking ABI compatibility of a compiled library against its
headers, you had to manually specify all compiler flags:

```bash
# Old workflow — error-prone, flags must match the real build exactly
abicheck dump libfoo.so -H include/ \
    --gcc-options "-std=c++17 -DFOO_ENABLE_SSL=1 -I/usr/include/openssl"
```

If even one `-D` flag or `-I` path was wrong, abicheck would parse headers
under a different configuration than the actual build, producing **false
positives** (reporting changes that don't exist) or **false negatives** (missing
real ABI breaks hidden behind `#ifdef` blocks).

### How it works now

Modern build systems (CMake, Meson, Ninja) can generate a `compile_commands.json`
file that captures the **exact compiler flags** for every source file. abicheck
now ingests this file directly:

```bash
# New workflow — deterministic, matches real build exactly
cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON .
cmake --build build

abicheck dump build/libfoo.so -H include/ -p build/
```

The `-p build/` flag tells abicheck to look for `build/compile_commands.json`
and derive all flags automatically: defines, include paths, language standard,
target triple, sysroot, and ABI-affecting options like `-fvisibility=hidden`.

### CLI options

| Flag | Description |
|------|-------------|
| `-p <dir>` / `--build-dir <dir>` | Build directory containing `compile_commands.json` |
| `--compile-db <file>` | Explicit path to `compile_commands.json` (alias for `-p`) |
| `--compile-db-filter <glob>` | Filter entries by source file pattern (e.g., `src/libfoo/**`) |

### When to use it

- **Multi-configuration builds**: Libraries with feature flags (`-DENABLE_SSL=1`)
  where different builds expose different ABI surfaces
- **Cross-compilation**: Target triple and sysroot are captured automatically
- **Large projects**: Instead of maintaining a separate list of flags for
  abicheck, the build system provides them
- **CI pipelines**: `compile_commands.json` is generated during the build step
  and consumed by the ABI check step — no manual synchronization needed

### Example: CMake project with feature flags

```bash
# Build with SSL enabled
cmake -B build-ssl -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DFOO_ENABLE_SSL=ON .
cmake --build build-ssl

# Dump ABI with exact build flags
abicheck dump build-ssl/libfoo.so -H include/ -p build-ssl/ -o baseline-ssl.json

# Build without SSL
cmake -B build-plain -DCMAKE_EXPORT_COMPILE_COMMANDS=ON -DFOO_ENABLE_SSL=OFF .
cmake --build build-plain

# Compare — abicheck uses the correct flags for each side
abicheck compare baseline-ssl.json build-plain/libfoo.so \
    --new-header include/ \
    --format markdown
```

### Interaction with existing flags

When both `-p` (compile database) and explicit flags (`--gcc-options`,
`--sysroot`, etc.) are specified, **explicit flags take precedence**. This lets
you override specific values while inheriting the rest from the build:

```bash
abicheck dump libfoo.so -H include/ -p build/ \
    --gcc-options "-DEXTRA_DEFINE=1"  # added on top of compile_commands.json flags
```

---

## 2. Debug Artifact Resolution

### The problem it solves

abicheck achieves its highest accuracy when it has access to DWARF debug
information (struct layouts, field offsets, calling conventions). But in many
real-world deployments, debug info is **not embedded** in the binary:

- **Stripped binaries**: Release builds remove debug sections for size
- **Split DWARF**: Debug info is in separate `.dwo` or `.dwp` files
- **Distro debug packages**: Fedora/Debian ship debuginfo in separate packages
  installed to `/usr/lib/debug/.build-id/`
- **macOS dSYM bundles**: Debug info lives in `.dSYM` directories
- **Windows PDB**: Debug info is in separate `.pdb` files

Previously, abicheck would silently fall back to symbols-only mode when debug
info wasn't embedded, missing many ABI checks.

### How it works now

abicheck now has a **resolver chain** that automatically searches for debug
artifacts across multiple locations:

```text
1. Embedded DWARF (binary itself has .debug_info)
2. Split DWARF (.dwo files or .dwp package)
3. Build-id tree (/usr/lib/debug/.build-id/<ab>/<cdef...>.debug)
4. Path mirror (/usr/lib/debug/usr/lib/libfoo.so.debug)
5. dSYM bundle (macOS: Foo.dylib.dSYM/Contents/Resources/DWARF/Foo.dylib)
6. PDB (Windows: adjacent .pdb or _NT_SYMBOL_PATH)
7. debuginfod (opt-in network: query by build-id)
```

### CLI options

| Flag | Description |
|------|-------------|
| `--debug-root <dir>` | Directory containing separate debug files. Can be repeated. |
| `--debug-root1 <dir>` | Debug root for old side only (compare command). |
| `--debug-root2 <dir>` | Debug root for new side only (compare command). |
| `--debuginfod` | Enable debuginfod network resolution (opt-in). |
| `--debuginfod-url <url>` | Override debuginfod server URL. |

### When to use it

- **Distro package comparisons**: Point to the debuginfo package extraction
  directory with `--debug-root`
- **CI with stripped builds**: Keep debug artifacts in a separate directory and
  pass it to abicheck
- **macOS frameworks**: dSYM bundles are found automatically when adjacent to
  the binary, or specify `--debug-root` for non-standard locations
- **Fedora/RHEL workflows**: debuginfod servers serve debug info for all
  packages — enable with `--debuginfod`

### Example: Comparing stripped distro packages

```bash
# Extract packages
rpm2cpio libfoo-1.0.rpm | cpio -idm -D old/
rpm2cpio libfoo-debuginfo-1.0.rpm | cpio -idm -D old-debug/
rpm2cpio libfoo-2.0.rpm | cpio -idm -D new/
rpm2cpio libfoo-debuginfo-2.0.rpm | cpio -idm -D new-debug/

# Compare with debug roots
abicheck compare \
    old/usr/lib64/libfoo.so.1 \
    new/usr/lib64/libfoo.so.1 \
    --debug-root1 old-debug/usr/lib/debug \
    --debug-root2 new-debug/usr/lib/debug \
    --format sarif -o abi-report.sarif
```

### Example: Using debuginfod for zero-config debug resolution

```bash
# Fedora/RHEL: debug info fetched automatically by build-id
export DEBUGINFOD_URLS="https://debuginfod.fedoraproject.org/"
abicheck compare old-libfoo.so new-libfoo.so --debuginfod
```

---

## 3. Baseline Registry

### The problem it solves

ABI checking in CI requires a **baseline** — a reference snapshot to compare
against. Previously, teams stored baselines ad-hoc: checked into git, uploaded
to S3, or generated fresh each CI run. There was no standard way to:

- Store baselines with version/platform/variant addressing
- Retrieve the correct baseline for a given comparison
- Verify baseline integrity (detect tampering or corruption)
- Manage baseline lifecycle (list, delete, retention)

### How it works now

abicheck has a new `baseline` command group that provides a standard workflow
for baseline management:

```bash
# After a release build, push the baseline
abicheck dump build/libfoo.so -H include/ -o snapshot.json
abicheck baseline push libfoo \
    --version 1.0.0 \
    --platform linux-x86_64 \
    --snapshot snapshot.json

# In a PR CI job, pull the baseline and compare
abicheck baseline pull libfoo:1.0.0:linux-x86_64 -o baseline.json
abicheck compare baseline.json build/libfoo.so -H include/ --format sarif

# List all baselines
abicheck baseline list
# Output:
#   libfoo/1.0.0/linux-x86_64
#   libfoo/2.0.0/linux-x86_64

# Delete an old baseline
abicheck baseline delete libfoo:0.9.0:linux-x86_64
```

### CLI commands

| Command | Description |
|---------|-------------|
| `abicheck baseline push <library>` | Store a baseline snapshot |
| `abicheck baseline pull <spec>` | Retrieve a baseline by key |
| `abicheck baseline list [prefix]` | List available baselines |
| `abicheck baseline delete <spec>` | Delete a baseline |

The spec format is `library:version:platform[:variant]`.

### Storage layout

Baselines are stored as plain files in a directory tree (default:
`.abicheck/baselines/`):

```
.abicheck/baselines/
├── libfoo/
│   ├── 1.0.0/
│   │   └── linux-x86_64/
│   │       ├── snapshot.json    # ABI snapshot
│   │       └── metadata.json    # Provenance + checksum
│   └── 2.0.0/
│       └── linux-x86_64/
│           ├── snapshot.json
│           └── metadata.json
└── libbar/
    └── 1.0.0/
        └── linux-x86_64/
            ├── snapshot.json
            └── metadata.json
```

### Integrity verification

Each pushed baseline includes a SHA-256 checksum in `metadata.json`. On pull,
the checksum is verified before the snapshot is returned. Metadata also records:

- abicheck version that produced the snapshot
- Timestamp of creation
- Optional git commit SHA
- Optional build-context hash (when `-p` was used)

### When to use it

- **CI/CD pipelines**: Push baselines on release, pull and compare on PRs
- **Multi-platform projects**: Store baselines per platform (`linux-x86_64`,
  `windows-x86_64`, `macos-arm64`)
- **Feature-flagged builds**: Use variants to track different build configs
  (`ssl-enabled`, `debug`, `minimal`)
- **Shared teams**: Use a network filesystem or shared directory as the registry
  root (`--registry /shared/abi-baselines`)

### Example: CI workflow (GitHub Actions)

```yaml
jobs:
  abi-check:
    steps:
      - uses: actions/checkout@v4

      - name: Build
        run: cmake --build build/

      - name: Dump ABI snapshot
        run: abicheck dump build/libfoo.so -H include/ -o snapshot.json

      - name: Pull baseline
        run: abicheck baseline pull libfoo:latest:linux-x86_64 -o baseline.json
             --registry .abicheck/baselines

      - name: Compare
        run: abicheck compare baseline.json snapshot.json --format sarif -o abi.sarif

      - name: Update baseline (on release tag)
        if: startsWith(github.ref, 'refs/tags/v')
        run: |
          abicheck baseline push libfoo \
            --version ${{ github.ref_name }} \
            --platform linux-x86_64 \
            --snapshot snapshot.json \
            --git-commit ${{ github.sha }}
```

---

## Summary of User Flow Improvements

| Before | After |
|--------|-------|
| Manually specify all compiler flags for header parsing | `-p build/` ingests exact flags from `compile_commands.json` |
| Stripped binaries fall back to symbols-only mode silently | `--debug-root` and `--debuginfod` find debug info automatically |
| Debug info in dSYM/PDB requires manual `--pdb-path` | Resolved automatically via pluggable resolver chain |
| Baselines stored ad-hoc (git, S3, regenerated) | `abicheck baseline push/pull/list/delete` with integrity checks |
| No standard way to address baselines by version/platform | `BaselineKey` with `library:version:platform:variant` addressing |
| No integrity verification for stored snapshots | SHA-256 checksums in metadata, verified on pull |
