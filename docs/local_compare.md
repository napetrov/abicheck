# Local Build Comparison & Snapshot Workflow

This guide covers how to compare locally built libraries against published releases
using `abi-scanner`, and how to pre-snapshot public baselines for fast offline CI.

---

## Overview

`abi-scanner` supports three spec types for the `compare` command:

| Spec format | Example | Description |
|-------------|---------|-------------|
| `apt:pkg=version` | `apt:intel-oneapi-dnnl=2025.2.0` | Download from Intel APT repo |
| `local:/path` | `local:./libdnnl.so` or `local:./my.deb` | Local file (.so, .deb, directory) |
| `dump:/path/to/file.abi` | `dump:~/.abi-snapshots/libdnnl.so-2025.2.abi` | Pre-saved abidw XML dump |

---

## Workflow 1: One-off — Compare Local Build vs Published Release

The simplest CI pattern: you build a `.deb`, pass it as the `new` side, and compare
against the last public release.

```bash
abi-scanner compare \
  apt:intel-oneapi-dnnl=2025.2.0 \
  local:/path/to/intel-oneapi-dnnl-2025.3.0-custom.deb \
  --library-name libdnnl.so \
  --apt-index-url https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz \
  --fail-on breaking
```

Expected output:
```
Comparing apt:intel-oneapi-dnnl=2025.2.0 → local:/path/to/intel-oneapi-dnnl-2025.3.0-custom.deb
Status: ✅ NO_CHANGE
```

**Exit codes:**

| Code | Meaning | CI action |
|------|---------|-----------|
| `0` | No ABI changes | ✅ Pass |
| `4` | Additions only (compatible) | ✅ Pass |
| `8` | Incompatible changes | ❌ Fail (with `--fail-on breaking`) |
| `12` | Breaking changes (removals) | ❌ Fail |

**Also works with a bare `.so` file:**
```bash
abi-scanner compare \
  apt:intel-oneapi-dnnl=2025.2.0 \
  local:/path/to/build/libdnnl.so \
  --library-name libdnnl.so \
  --apt-index-url https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz
```

---

## Workflow 2: Pre-snapshot + Compare (Offline / Fast CI)

For teams that want **reproducible baselines** stored in git or an artifact registry,
and don't want CI to download packages on every PR build.

### Step 1: Snapshot the current public release (do this once, e.g. nightly)

```bash
mkdir -p ~/.abi-snapshots/dnnl

abi-scanner snapshot \
  apt:intel-oneapi-dnnl=2025.2.0 \
  --output-dir ~/.abi-snapshots/dnnl \
  --apt-index-url https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz \
  --library-name libdnnl.so \
  -v
```

Output:
```
Saved: /home/user/.abi-snapshots/dnnl/libdnnl.so-2025.2.0.abi
Saved: /home/user/.abi-snapshots/dnnl/snapshot.json
```

If `--library-name` is omitted, **all** `.so` files in the package are dumped:
```
Saved: /home/user/.abi-snapshots/dnnl/libdnnl.so-2025.2.0.abi
Saved: /home/user/.abi-snapshots/dnnl/libdnnl_sycl.so-2025.2.0.abi
Saved: /home/user/.abi-snapshots/dnnl/snapshot.json
```

### Step 2: Compare local build against snapshot (fast, no network)

```bash
abi-scanner compare \
  dump:~/.abi-snapshots/dnnl/libdnnl.so-2025.2.0.abi \
  local:/path/to/my-build/libdnnl.so \
  --fail-on breaking
```

This is **instant** — no download, no abidw on the baseline side. Only the new
`.so` is processed.

---

## Workflow 3: Compare Two Snapshots

```bash
abi-scanner compare \
  dump:~/.abi-snapshots/dnnl/libdnnl.so-2025.2.0.abi \
  dump:~/.abi-snapshots/dnnl/libdnnl.so-2025.3.0.abi
```

Both sides use pre-saved dumps. No packages downloaded, no `abidw` invocations.

---

## Manifest File Format

Every `snapshot` run writes a `snapshot.json` manifest alongside the `.abi` files:

```json
{
  "spec": "apt:intel-oneapi-dnnl=2025.2.0",
  "timestamp": "2025-03-05T12:00:00Z",
  "dumps": [
    {
      "library": "libdnnl.so",
      "path": "/home/user/.abi-snapshots/dnnl/libdnnl.so-2025.2.0.abi",
      "size_bytes": 48291
    }
  ]
}
```

Fields:

| Field | Description |
|-------|-------------|
| `spec` | Original package spec used for the snapshot |
| `timestamp` | UTC ISO-8601 timestamp when snapshot was created |
| `dumps[].library` | Base `.so` name (e.g. `libdnnl.so`) |
| `dumps[].path` | Absolute path to the `.abi` file |
| `dumps[].size_bytes` | File size of the dump |

---

## Finding `--apt-index-url` and `--apt-pkg-pattern`

### Intel oneAPI APT Repository

```
https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz
```

This index covers all Intel oneAPI packages across distributions (Ubuntu, Debian).

### Listing available packages and versions

```bash
# List all versions of intel-oneapi-dnnl from APT
abi-scanner list apt:intel-oneapi-dnnl \
  --apt-index-url https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz \
  --apt-pkg-pattern '^intel-oneapi-dnnl='
```

### Package naming patterns

| Library | Package name pattern | Library file |
|---------|---------------------|--------------|
| oneDNN | `intel-oneapi-dnnl=<ver>` | `libdnnl.so` |
| oneCCL | `intel-oneapi-ccl=<ver>` | `libccl.so` |
| DPC++ runtime | `intel-oneapi-compiler-dpcpp-cpp-runtime-<year>=<ver>` | `libsycl.so` |
| MKL | `intel-oneapi-mkl=<ver>` | `libmkl_rt.so` |

---

## Snapshotting Multiple Libraries

### Option A: Specify `--library-name` per invocation

```bash
abi-scanner snapshot apt:intel-oneapi-dnnl=2025.2.0 \
  --output-dir ~/.abi-snapshots/dnnl \
  --library-name libdnnl.so

abi-scanner snapshot apt:intel-oneapi-dnnl=2025.2.0 \
  --output-dir ~/.abi-snapshots/dnnl \
  --library-name libdnnl_sycl.so
```

### Option B: Omit `--library-name` to capture all `.so` files

```bash
abi-scanner snapshot apt:intel-oneapi-dnnl=2025.2.0 \
  --output-dir ~/.abi-snapshots/dnnl
# → saves libdnnl.so-2025.2.0.abi, libdnnl_sycl.so-2025.2.0.abi, snapshot.json
```

---

## Recommended CI Integration Pattern

### Nightly job: update snapshots

```yaml
# .github/workflows/abi-snapshot.yml
name: ABI Snapshot (nightly)
on:
  schedule:
    - cron: '0 2 * * *'   # 2am UTC daily

jobs:
  snapshot:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get install -y abigail-tools
      - run: pip install abi-scanner

      - name: Snapshot baseline
        run: |
          abi-scanner snapshot apt:intel-oneapi-dnnl=2025.2.0 \
            --output-dir abi-baselines/dnnl \
            --apt-index-url https://apt.repos.intel.com/oneapi/dists/all/main/binary-amd64/Packages.gz

      - name: Commit updated snapshots
        run: |
          git config user.email "ci@example.com"
          git config user.name "CI Bot"
          git add abi-baselines/
          git diff --cached --quiet || git commit -m "chore: update ABI snapshots"
          git push
```

### PR job: compare against snapshot

```yaml
# .github/workflows/abi-check.yml
name: ABI Compatibility Check
on: [pull_request]

jobs:
  abi-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: sudo apt-get install -y abigail-tools
      - run: pip install abi-scanner

      - name: Build library
        run: cmake --build build --target dnnl

      - name: ABI check vs snapshot
        run: |
          abi-scanner compare \
            dump:abi-baselines/dnnl/libdnnl.so-2025.2.0.abi \
            local:build/src/libdnnl.so \
            --fail-on breaking
```

**Why this pattern is superior to downloading on every PR:**

- ✅ No network dependency in PR jobs
- ✅ Snapshot is versioned and reproducible (committed to git)
- ✅ Baseline can be audited (`.abi` XML is human-readable)
- ✅ Teams can store snapshots in artifact registries (S3, GitHub Releases, etc.)
- ✅ Works in air-gapped environments after initial snapshot

---

## See Also

- [Getting Started](getting_started.md) — Getting started with all commands
- [Gap Report](gap_report.md) — Coverage analysis vs ABICC/libabigail
