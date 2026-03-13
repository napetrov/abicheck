# abicheck

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/napetrov/abicheck/branch/main/graph/badge.svg)](https://codecov.io/gh/napetrov/abicheck)

**abicheck checks C/C++ library compatibility at both API and ABI levels.**

> **Platform support:** Linux only (ELF/DWARF). Windows (PE) and macOS (Mach-O) are not yet supported.

abicheck is designed as a **drop-in replacement for [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/)**
with a modern, maintainable Python codebase. It is inspired by both ABICC and
[libabigail / abidiff](https://sourceware.org/libabigail/) — many thanks and kudos
to both communities for defining the practical ABI-checking ecosystem.

---

## Installation

> **Note:** abicheck is not yet published to PyPI or conda-forge. Install from source for now.

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Linux** | ELF/DWARF only |
| **Python >= 3.10** | |
| **`castxml`** | Required for `dump` command (header-based analysis) |
| **`g++` or `clang++`** | Must be accessible to castxml |

```bash
# Install castxml
sudo apt install castxml g++          # Ubuntu/Debian
# or
conda install -c conda-forge castxml  # conda
```

### Install from source

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e .

# Contributor / development install (includes test & lint dependencies):
# pip install -e ".[dev]"
```

---

## Quick start

### 1) Compare two libraries directly (primary flow)

The simplest way to check ABI compatibility — pass two `.so` files and their
public headers. Each library version gets its own header(s):

```bash
# Each version has its own header
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h

# Multiple headers per version
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --old-header include/v1/bar.h \
  --new-header include/v2/foo.h --new-header include/v2/bar.h

# Shorthand: -H applies the same header to both sides
# (only when the header itself didn't change between versions)
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h

# With version labels
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h \
  --old-version 1.0 --new-version 2.0

# Output formats: markdown (default), json, sarif, html
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header v1/foo.h --new-header v2/foo.h --format sarif -o abi.sarif

# Policy and suppression
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header v1/foo.h --new-header v2/foo.h --policy sdk_vendor
```

`compare` auto-detects each input: `.so` files are dumped on-the-fly, `.json`
snapshots and ABICC Perl dumps (Data::Dumper `.dump` files) are loaded directly.
You can mix them freely.

### 2) Dump snapshots and compare later (secondary flow)

When you want to cache ABI baselines (e.g. store snapshots as CI artifacts or
commit them to the repo), use the explicit two-step workflow:

```bash
# Step 1: Create snapshots (each version uses its own header)
abicheck dump libfoo.so.1 -H include/v1/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/v2/foo.h --version 2.0 -o libfoo-2.0.json

# Step 2: Compare snapshots (no headers needed — already baked in)
abicheck compare libfoo-1.0.json libfoo-2.0.json

# Output formats and policies work the same way
abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o abi.sarif
abicheck compare libfoo-1.0.json libfoo-2.0.json --policy sdk_vendor
```

#### Language mode and cross-compilation

```bash
# Pure C library (default is C++)
abicheck dump libfoo.so -H foo.h --lang c -o snap.json
abicheck compare libv1.so libv2.so -H foo.h --lang c

# Cross-compilation (aarch64 example)
abicheck dump libfoo.so -H include/foo.h \
  --gcc-prefix aarch64-linux-gnu- \
  --sysroot /opt/sysroots/aarch64 \
  -o snap.json
```

Cross-compilation flags: `--gcc-path`, `--gcc-prefix`, `--gcc-options`, `--sysroot`, `--nostdinc`.

Add `-v` / `--verbose` to any command for debug output.

### 3) Compare snapshot baseline vs current build (mixed mode)

Ideal for CI: store a baseline snapshot from a known release, compare against
the freshly built `.so`:

```bash
# Compare stored baseline against current build
abicheck compare baseline-1.0.json ./build/libfoo.so \
  --new-header include/foo.h --new-version 2.0-dev

# Or the other way: live old build vs stored new snapshot
abicheck compare ./build-old/libfoo.so new-release.json \
  --old-header include/foo.h --old-version 1.0-rc1
```

**Policy file example** (`project_policy.yaml`):
```yaml
base_policy: strict_abi
overrides:
  enum_member_renamed: ignore   # break | warn | ignore
  field_renamed: ignore
```

### 4) ABICC-compatible mode (for migration from ABICC)

For teams migrating from `abi-compliance-checker` — same flags, same XML
descriptor format:

```bash
# Minimal (same flags as abi-compliance-checker):
abicheck compat check -lib foo -old old.xml -new new.xml

# Full flag parity:
abicheck compat check -lib foo -old old.xml -new new.xml \
  -report-path report.html \
  -s \
  -show-retval \
  -v1 1.0 -v2 2.0
```

This mode supports ABICC-style descriptor workflows so teams can migrate without
rewriting their entire pipeline on day one. See [ABICC compatibility reference](docs/abicc_compat.md) for full flag list.

> Note: `compat` now supports minimal ABICC Perl `ABI.dump` (`Data::Dumper`) input for migration workflows.
> ABICC XML dump variants (`<ABI_dump...>` / `<abi_dump...>`) are still unsupported.

---

## ABICC drop-in replacement

Existing ABICC pipelines work with a one-line swap:

```bash
# Before:
abi-compliance-checker -lib libfoo -old old.xml -new new.xml -report-path r.html

# After (identical flags):
abicheck compat check -lib libdnnl -old old.xml -new new.xml -report-path r.html
```

Migration path:

1. Keep your existing XML descriptor generation.
2. Replace ABICC CLI call with `abicheck compat check` (same flags, same XML).
3. Move to `abicheck compare lib.so.1 lib.so.2 -H ...` for the simplest one-liner workflow.
4. Optionally use `dump` + `compare` when you want explicit snapshot caching for CI baselines.

See [ABICC compatibility reference](docs/abicc_compat.md) and [Migration guide](docs/migration/from_abicc.md) for full flag list and details.

---

## GitHub Actions integration

```yaml
steps:
  - name: Dump ABI snapshots
    run: |
      abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o old.json
      abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o new.json

  - name: Compare ABI
    run: abicheck compare old.json new.json --format sarif -o abi.sarif

  - uses: github/codeql-action/upload-sarif@v3
    if: always()
    with:
      sarif_file: abi.sarif
```

Exit codes for CI gates: `0` = compatible/no_change, `1` = tool/runtime error, `2` = API break, `4` = breaking ABI change.
See [Exit Codes](docs/exit_codes.md) for full reference including `compat` mode.

---

## Benchmark results

abicheck achieves **100% accuracy** across 42 benchmarked cases covering all major ABI break
categories (symbol removal, struct layout, vtable drift, enum changes, calling convention, etc.):

| Tool | Correct / Scored | Accuracy |
|------|-----------------|----------|
| **abicheck (compare)** | **42/42** | **100%** |
| abicheck (compat) | 40/42 | 95% |
| ABICC (xml) | 25/41 | 61% |
| ABICC (abi-dumper) | 20/30 | 66% |
| abidiff | 11/42 | 26% |

See [Benchmark report](docs/benchmark_report.md) and [Tool comparison](docs/tool_comparison.md)
for per-case analysis, timing data, and methodology.

---

## Documentation

- **[Getting started](docs/getting_started.md)** — installation, first check, CI setup
- **[Verdicts](docs/concepts/verdicts.md)** — Source-level / BREAKING / API_BREAK / COMPATIBLE / NO_CHANGE
- **[Exit Codes](docs/exit_codes.md)** — CI-ready exit code reference
- **[Policy Profiles](docs/policies.md)** — built-in and custom policies
- **[ABICC Migration](docs/migration/from_abicc.md)** — migrating from abi-compliance-checker
- **[ABI Break Catalog](docs/abi_breaking_cases_catalog.md)** — documented break scenarios (cases 01–29)
- **[Examples](examples/README.md)** — runnable C/C++ examples with expected verdicts
- **[Tool Comparison](docs/tool_comparison.md)** — abicheck vs abidiff vs ABICC
- **[Architecture](docs/reference/architecture.md)** — pipeline, modules, and design
- **[Benchmark Report](docs/benchmark_report.md)** — full per-case results

---

## Testing

```bash
# Fast tests (default CI gate)
pytest tests/ -v --tb=short -m "not integration and not libabigail and not abicc" \
  --cov=abicheck --cov-report=term-missing

# Full suite (requires castxml, abidiff, abi-compliance-checker)
pytest --cov=abicheck --cov-report=term-missing
```

---

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
