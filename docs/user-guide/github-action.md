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
| `mode` | no | `compare` (default), `dump`, `deps`, or `stack-check` |
| `old-library` | yes (compare) | Path to old library, JSON snapshot, or ABICC dump |
| `new-library` | yes | Path to new library or binary |

### Header inputs

| Input | Required | Description |
|-------|----------|-------------|
| `header` | no | Public header file(s) or directory(ies) for both sides (space-separated) |
| `old-header` | no | Header file(s) or directory(ies) for old side only |
| `new-header` | no | Header file(s) or directory(ies) for new side only |
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

### Full-stack dependency validation (Linux ELF)

| Input | Default | Description |
|-------|---------|-------------|
| `follow-deps` | `false` | Include transitive dependency graph and symbol bindings in dump/compare output |
| `baseline` | — | Sysroot for baseline environment (required for `stack-check` mode) |
| `candidate` | — | Sysroot for candidate environment (required for `stack-check` mode) |
| `search-path` | — | Additional library search directories (space-separated) |
| `ld-library-path` | — | Simulated `LD_LIBRARY_PATH` (colon-separated) |

### Output and policy

| Input | Default | Description |
|-------|---------|-------------|
| `format` | `markdown` | Output format: `markdown`, `json`, `sarif`, `html` |
| `output-file` | — | Path to write report (auto-set for SARIF) |
| `policy` | `strict_abi` | Built-in policy: `strict_abi`, `sdk_vendor`, `plugin_abi` |
| `policy-file` | — | Custom YAML policy file |
| `suppress` | — | YAML suppression file (supports `label`, `source_location`, `expires`) |
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
| `verdict` | **compare/dump:** `COMPATIBLE`, `ADDITIONS`, `API_BREAK`, `BREAKING`, or `ERROR`. **stack-check:** `PASS`, `WARN`, `FAIL`, or `ERROR`. **deps:** `PASS`, `FAIL`, or `ERROR`. |
| `exit-code` | **compare:** `0` (compatible), `1` (additions), `2` (API break), `4` (ABI break). **stack-check:** `0` (pass), `1` (warn), `4` (fail). **deps:** `0` (ok), `1` (missing). |
| `report-path` | Path to the generated report file (empty when no output file was produced) |

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
          key: abi-baseline-${{ github.event.repository.default_branch }}-${{ github.sha }}
          restore-keys: |
            abi-baseline-${{ github.event.repository.default_branch }}-

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

### Cross-compilation check (dump mode)

Cross-compilation flags (`gcc-prefix`, `sysroot`, `gcc-options`) are only supported
in `dump` mode. Use `mode: dump` to generate a baseline from a cross-compiled binary,
then compare with a separate step.

```yaml
      # Step 1: dump ABI snapshot from cross-compiled binary
      - uses: napetrov/abicheck@v1
        with:
          mode: dump
          new-library: build-arm64/libfoo.so
          header: include/foo.h
          gcc-prefix: aarch64-linux-gnu-
          sysroot: /usr/aarch64-linux-gnu
          lang: c
          output-file: baseline-arm64.json
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

### Matrix: multiple platforms (native scan per OS)

Use native runners to get the best platform-specific signal (Linux/ELF, macOS/Mach-O, Windows/PE):

```yaml
jobs:
  abi-scan:
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            ext: so
          - os: macos-latest
            ext: dylib
          - os: windows-latest
            ext: dll
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4

      # Build your platform artifact here (example command only)
      - name: Build
        run: |
          echo "build on ${{ matrix.os }}"

      - name: ABI compare (native)
        uses: napetrov/abicheck@v1
        with:
          old-library: baselines/${{ runner.os }}/abi-old.json
          new-library: build/${{ runner.os }}/libfoo.${{ matrix.ext }}
          new-header: include/foo.h
          format: json
          output-file: abi-report-${{ runner.os }}.json

      - name: Upload platform ABI report
        uses: actions/upload-artifact@v4
        with:
          name: abi-report-${{ runner.os }}
          path: abi-report-${{ runner.os }}.json
```

### Skip system dependency installation

If `castxml` + compiler are already available (custom image, pre-provisioned VM,
or conda-forge environment), set `install-deps: false`:

```yaml
      - uses: napetrov/abicheck@v1
        with:
          old-library: old.json
          new-library: new.json
          install-deps: false
```

Example (conda-forge pre-step):

```yaml
      - name: Install abicheck from conda-forge
        run: |
          conda install -y -c conda-forge abicheck

      - uses: napetrov/abicheck@v1
        with:
          old-library: old.json
          new-library: new.json
          install-deps: false
```

When comparing two JSON snapshots, no header-analysis toolchain is needed.

### Full-stack dependency check on container image update

Validate that updating a base image doesn't break your application's dependency
stack. This runs `stack-check` to compare the binary's full transitive
dependency tree across old and new container root filesystems:

```yaml
jobs:
  stack-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Extract old rootfs
        run: |
          docker export $(docker create old-image:latest) | tar -xf - -C /tmp/old-root

      - name: Extract new rootfs
        run: |
          docker export $(docker create new-image:latest) | tar -xf - -C /tmp/new-root

      - name: Full-stack ABI check
        uses: napetrov/abicheck@v1
        with:
          mode: stack-check
          new-library: usr/bin/myapp
          baseline: /tmp/old-root
          candidate: /tmp/new-root
          format: json
          output-file: stack-report.json
```

Exit codes for `stack-check`: `0` = PASS, `1` = WARN (ABI risk), `4` = FAIL (load failure or ABI break).

### Dependency tree audit

Show the resolved dependency tree and symbol binding status for a binary.
Useful for auditing which libraries a binary actually loads and detecting
missing dependencies before deployment:

```yaml
      - name: Audit dependencies
        uses: napetrov/abicheck@v1
        with:
          mode: deps
          new-library: build/myapp
          sysroot: /path/to/target/rootfs
```

### Include dependency info in compare

Add `follow-deps: true` to include the transitive dependency graph and symbol
binding information alongside the regular ABI diff:

```yaml
      - name: Compare with dependency context
        uses: napetrov/abicheck@v1
        with:
          old-library: baseline.json
          new-library: build/libfoo.so
          new-header: include/foo.h
          follow-deps: true
```

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
