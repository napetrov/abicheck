# Local Build Comparison & Snapshot Workflow

This guide covers how to compare locally built libraries against published releases
using `abi-scanner`, and how to pre-snapshot public baselines for fast offline CI.

---

## Overview

`abi-scanner` supports three spec types for the `compare` command:

| Spec format | Example | Description |
|-------------|---------|-------------|
| `apt:pkg=version` | `apt:libfoo-dev=2.0.0` | Download from APT repo |
| `local:/path` | `local:./libfoo.so` or `local:./my.deb` | Local file (.so, .deb, directory) |
| `dump:/path/to/file.abi` | `dump:~/.abi-snapshots/libfoo.so-2.0.abi` | Pre-saved abidw XML dump |

---

## Workflow 1: One-off — Compare Local Build vs Published Release

The simplest CI pattern: you build a `.deb`, pass it as the `new` side, and compare
against the last public release.

```bash
abi-scanner compare \
  apt:libfoo-dev=2.0.0 \
  local:/path/to/libfoo-dev-2.1.0-custom.deb \
  --library-name libfoo.so \
  --apt-index-url https://apt.example.com/repo/dists/stable/main/binary-amd64/Packages.gz \
  --fail-on breaking
```

Expected output:
```
Comparing apt:libfoo-dev=2.0.0 → local:/path/to/libfoo-dev-2.1.0-custom.deb
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
  apt:libfoo-dev=2.0.0 \
  local:/path/to/build/libfoo.so \
  --library-name libfoo.so \
  --apt-index-url https://apt.example.com/repo/dists/stable/main/binary-amd64/Packages.gz
```

---

## Workflow 2: Pre-snapshot + Compare (Offline / Fast CI)

For teams that want **reproducible baselines** stored in git or an artifact registry,
and don't want CI to download packages on every PR build.

### Step 1: Snapshot the current public release (do this once, e.g. nightly)

```bash
mkdir -p ~/.abi-snapshots/foo

abi-scanner snapshot \
  apt:libfoo-dev=2.0.0 \
  --output-dir ~/.abi-snapshots/foo \
  --apt-index-url https://apt.example.com/repo/dists/stable/main/binary-amd64/Packages.gz \
  --library-name libfoo.so \
  -v
```

Output:
```
Saved: /home/user/.abi-snapshots/foo/libfoo.so-2.0.0.abi
Saved: /home/user/.abi-snapshots/foo/snapshot.json
```

If `--library-name` is omitted, **all** `.so` files in the package are dumped:
```
Saved: /home/user/.abi-snapshots/foo/libfoo.so-2.0.0.abi
Saved: /home/user/.abi-snapshots/foo/libfoo_extra.so-2.0.0.abi
Saved: /home/user/.abi-snapshots/foo/snapshot.json
```

### Step 2: Compare local build against snapshot (fast, no network)

```bash
abi-scanner compare \
  dump:~/.abi-snapshots/foo/libfoo.so-2.0.0.abi \
  local:/path/to/my-build/libfoo.so \
  --fail-on breaking
```

This is **instant** — no download, no abidw on the baseline side. Only the new
`.so` is processed.

---

## Workflow 3: Compare Two Snapshots

```bash
abi-scanner compare \
  dump:~/.abi-snapshots/foo/libfoo.so-2.0.0.abi \
  dump:~/.abi-snapshots/foo/libfoo.so-2.1.0.abi
```

Both sides use pre-saved dumps. No packages downloaded, no `abidw` invocations.

---

## Manifest File Format

Every `snapshot` run writes a `snapshot.json` manifest alongside the `.abi` files:

```json
{
  "spec": "apt:libfoo-dev=2.0.0",
  "timestamp": "2025-03-05T12:00:00Z",
  "dumps": [
    {
      "library": "libfoo.so",
      "path": "/home/user/.abi-snapshots/foo/libfoo.so-2.0.0.abi",
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
| `dumps[].library` | Base `.so` name (e.g. `libfoo.so`) |
| `dumps[].path` | Absolute path to the `.abi` file |
| `dumps[].size_bytes` | File size of the dump |

---

## Finding `--apt-index-url` and `--apt-pkg-pattern`

### APT Repository Index

Most APT repositories publish a `Packages.gz` index. For example:

```
https://apt.example.com/repo/dists/stable/main/binary-amd64/Packages.gz
```

This index covers all packages in the repository across distributions (Ubuntu, Debian).

### Listing available packages and versions

```bash
# List all versions of libfoo-dev from APT
abi-scanner list apt:libfoo-dev \
  --apt-index-url https://apt.example.com/repo/dists/stable/main/binary-amd64/Packages.gz \
  --apt-pkg-pattern '^libfoo-dev='
```

### Package naming patterns

| Library | Package name pattern | Library file |
|---------|---------------------|--------------|
| libfoo | `libfoo-dev=<ver>` | `libfoo.so` |
| libbar | `libbar-dev=<ver>` | `libbar.so` |
| libcrypto | `libssl-dev=<ver>` | `libcrypto.so` |
| zlib | `zlib1g-dev=<ver>` | `libz.so` |

---

## Snapshotting Multiple Libraries

### Option A: Specify `--library-name` per invocation

```bash
abi-scanner snapshot apt:libfoo-dev=2.0.0 \
  --output-dir ~/.abi-snapshots/foo \
  --library-name libfoo.so

abi-scanner snapshot apt:libfoo-dev=2.0.0 \
  --output-dir ~/.abi-snapshots/foo \
  --library-name libfoo_extra.so
```

### Option B: Omit `--library-name` to capture all `.so` files

```bash
abi-scanner snapshot apt:libfoo-dev=2.0.0 \
  --output-dir ~/.abi-snapshots/foo
# → saves libfoo.so-2.0.0.abi, libfoo_extra.so-2.0.0.abi, snapshot.json
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
          abi-scanner snapshot apt:libfoo-dev=2.0.0 \
            --output-dir abi-baselines/foo \
            --apt-index-url https://apt.example.com/repo/dists/stable/main/binary-amd64/Packages.gz

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
        run: cmake --build build --target foo

      - name: ABI check vs snapshot
        run: |
          abi-scanner compare \
            dump:abi-baselines/foo/libfoo.so-2.0.0.abi \
            local:build/src/libfoo.so \
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

- [Getting Started](../getting-started.md) — Getting started with all commands
- [Gap Report](../development/abicc-parity-status.md) — Coverage analysis vs ABICC/libabigail
