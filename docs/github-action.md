# GitHub Action

abicheck ships as a reusable GitHub Action that you can add to any CI pipeline
with a few lines of YAML. It installs Python, system dependencies, and abicheck
automatically, then runs ABI comparison and reports results.

## Quick start

```yaml
- uses: napetrov/abicheck@v1
  with:
    old-library: abi-baseline.json
    new-library: build/libfoo.so
    new-header: include/foo.h
```

## Inputs

### Library inputs

| Input | Required | Description |
|-------|----------|-------------|
| `mode` | no | `compare` (default) or `dump` |
| `old-library` | yes (compare) | Path to old library, JSON snapshot, or ABICC dump |
| `new-library` | yes | Path to new library or binary |

### Header inputs

| Input | Required | Description |
|-------|----------|-------------|
| `header` | no | Public header(s) for both sides (space-separated) |
| `old-header` | no | Header(s) for old side only |
| `new-header` | no | Header(s) for new side only |
| `include` | no | Extra include dirs for castxml (both sides) |
| `old-include` | no | Include dirs for old side only |
| `new-include` | no | Include dirs for new side only |

### Version labels

| Input | Default | Description |
|-------|---------|-------------|
| `old-version` | `old` | Version label for old library |
| `new-version` | `new` | Version label for new library |

### Language and compiler

| Input | Default | Description |
|-------|---------|-------------|
| `lang` | `c++` | Language mode: `c++` or `c` |
| `gcc-path` | — | Path to cross-compiler binary (dump mode only) |
| `gcc-prefix` | — | Cross-toolchain prefix, e.g. `aarch64-linux-gnu-` (dump mode only) |
| `gcc-options` | — | Extra flags for castxml (dump mode only) |
| `sysroot` | — | Alternative system root (dump mode only) |
| `nostdinc` | `false` | Skip standard include paths (dump mode only) |

### Output and policy

| Input | Default | Description |
|-------|---------|-------------|
| `format` | `markdown` | Output format: `markdown`, `json`, `sarif`, `html` |
| `output-file` | — | Path to write report (auto-set for SARIF) |
| `policy` | `strict_abi` | Built-in policy: `strict_abi`, `sdk_vendor`, `plugin_abi` |
| `policy-file` | — | Custom YAML policy file |
| `suppress` | — | YAML suppression file |
| `verbose` | `false` | Enable debug output |

### Action behavior

| Input | Default | Description |
|-------|---------|-------------|
| `python-version` | `3.13` | Python version for setup-python |
| `install-deps` | `true` | Install castxml + gcc automatically |
| `upload-sarif` | `false` | Upload SARIF to GitHub Code Scanning |
| `fail-on-breaking` | `true` | Fail step on binary ABI break |
| `fail-on-api-break` | `false` | Fail step on source-level API break |
| `fail-on-additions` | `false` | Fail step when new public symbols/types are added (detects unintentional API expansion) |
| `add-job-summary` | `true` | Write summary to Job Summary panel |

## Outputs

| Output | Description |
|--------|-------------|
| `verdict` | `COMPATIBLE`, `ADDITIONS`, `API_BREAK`, `BREAKING`, or `ERROR` |
| `exit-code` | `0` (compatible), `1` (API additions), `2` (API break), `4` (ABI break) |
| `report-path` | Path to the generated report file |

## Usage examples

### Compare two libraries on a PR

```yaml
name: ABI Check
on: [pull_request]

jobs:
  abi-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build library
        run: mkdir build && cd build && cmake .. && make

      - name: Check ABI compatibility
        uses: napetrov/abicheck@v1
        with:
          old-library: abi-baseline.json  # committed to repo
          new-library: build/libfoo.so
          new-header: include/foo.h
          new-version: pr-${{ github.event.pull_request.number }}
```

### Save a baseline on release

The baseline is a JSON snapshot of the library's ABI surface. Generate it when
you release a version, then compare against it on every PR.

```yaml
name: ABI Baseline
on:
  release:
    types: [published]

jobs:
  save-baseline:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build library
        run: mkdir build && cd build && cmake .. && make

      - name: Dump ABI baseline
        uses: napetrov/abicheck@v1
        with:
          mode: dump
          new-library: build/libfoo.so
          header: include/foo.h
          new-version: ${{ github.ref_name }}
          output-file: abi-baseline.json

      - name: Upload baseline as release asset
        uses: softprops/action-gh-release@v2
        with:
          files: abi-baseline.json
```

### Download baseline and compare on PR

```yaml
      - name: Download baseline from latest release
        run: gh release download --pattern 'abi-baseline.json' --dir .
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}

      - name: Check ABI
        uses: napetrov/abicheck@v1
        with:
          old-library: abi-baseline.json
          new-library: build/libfoo.so
          new-header: include/foo.h
```

### Use GitHub Actions cache for baseline

```yaml
      - name: Restore cached baseline
        uses: actions/cache@v4
        with:
          path: abi-baseline.json
          key: abi-baseline-${{ github.event.repository.default_branch }}

      - name: Check ABI
        uses: napetrov/abicheck@v1
        with:
          old-library: abi-baseline.json
          new-library: build/libfoo.so
          new-header: include/foo.h
```

### SARIF with GitHub Code Scanning

Upload results to the Security tab so ABI breaks appear as code scanning alerts.

!!! note
    Requires `security-events: write` permission. On PRs, GitHub only shows
    **new** alerts introduced by the PR — existing alerts stay on the default
    branch and don't clutter the review.

```yaml
jobs:
  abi-check:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - run: mkdir build && cd build && cmake .. && make

      - uses: napetrov/abicheck@v1
        with:
          old-library: abi-baseline.json
          new-library: build/libfoo.so
          new-header: include/foo.h
          format: sarif
          upload-sarif: true
```

### Cross-compilation check

```yaml
      - uses: napetrov/abicheck@v1
        with:
          old-library: baseline-arm64.json
          new-library: build-arm64/libfoo.so
          new-header: include/foo.h
          gcc-prefix: aarch64-linux-gnu-
          sysroot: /usr/aarch64-linux-gnu
          lang: c
```

### Matrix: multiple libraries

```yaml
    strategy:
      matrix:
        lib:
          - { name: libfoo, so: build/libfoo.so, header: include/foo.h }
          - { name: libbar, so: build/libbar.so, header: include/bar.h }
    steps:
      - uses: napetrov/abicheck@v1
        with:
          old-library: baselines/${{ matrix.lib.name }}.json
          new-library: ${{ matrix.lib.so }}
          new-header: ${{ matrix.lib.header }}
```

### Skip system dependency installation

If castxml and gcc are already installed (e.g. in a custom Docker image or
a previous step), set `install-deps: false`:

```yaml
      - uses: napetrov/abicheck@v1
        with:
          old-library: old.json
          new-library: new.json
          install-deps: false
```

When comparing two JSON snapshots, no system dependencies are needed at all.

### Conditional failure

Allow API breaks but block binary ABI breaks:

```yaml
      - uses: napetrov/abicheck@v1
        with:
          old-library: baseline.json
          new-library: build/libfoo.so
          new-header: include/foo.h
          fail-on-breaking: true
          fail-on-api-break: false
```

### Detect unintentional API expansion

Block PRs that accidentally add new public symbols or types:

```yaml
      - uses: napetrov/abicheck@v1
        with:
          old-library: baseline.json
          new-library: build/libfoo.so
          new-header: include/foo.h
          fail-on-breaking: true
          fail-on-additions: true   # exit code 1 if any new public API appears
```

When `fail-on-additions: true`:
- Exit code `1` → new public symbol/type added (`verdict: ADDITIONS`)
- Exit code `0` → no additions, no breaks (`verdict: COMPATIBLE`)
- Exit code `4` → binary ABI break (`verdict: BREAKING`)

This is useful when your library has a stable frozen API and any expansion
must be a deliberate, reviewed decision rather than an accidental side effect.

## Versioning

The action follows [semantic versioning](https://semver.org/) with floating
major version tags:

```yaml
uses: napetrov/abicheck@v1         # latest stable v1.x.x (recommended)
uses: napetrov/abicheck@v1.2.0     # exact version (reproducible)
uses: napetrov/abicheck@abc123def  # exact commit SHA (most secure)
```

The `v1` tag is updated with each patch/minor release. Breaking changes to
the action interface will increment to `v2`.
