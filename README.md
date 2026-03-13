# abicheck

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/napetrov/abicheck/branch/main/graph/badge.svg)](https://codecov.io/gh/napetrov/abicheck)
[![PyPI](https://img.shields.io/pypi/v/abicheck.svg)](https://pypi.org/project/abicheck/)

**abicheck checks C/C++ library compatibility at both API and ABI levels.**

> **Platform support:** Linux only (ELF/DWARF). Windows (PE) and macOS (Mach-O) are not yet supported.

abicheck is designed as a **drop-in replacement for [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/)**
with a modern, maintainable Python codebase. It is inspired by both ABICC and
[libabigail / abidiff](https://sourceware.org/libabigail/) — many thanks and kudos
to both communities for defining the practical ABI-checking ecosystem.

---

## Installation

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Linux** | ELF/DWARF only |
| **Python >= 3.10** | |
| **`castxml`** | Required for `dump` command (header-based analysis) |
| **`g++` or `clang++`** | Must be accessible to castxml |

```bash
# Install castxml via pip (recommended — no system package needed)
pip install castxml

# Or via system package manager
sudo apt install castxml g++          # Ubuntu/Debian
conda install -c conda-forge castxml  # conda
```

### Install abicheck

```bash
pip install abicheck
abicheck --version
```

For development from source:

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e ".[dev]"
```

---

## Quick start

### 1) Create ABI snapshots

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o libfoo-2.0.json
```

### 2) Compare snapshots

```bash
# Markdown report (default)
abicheck compare libfoo-1.0.json libfoo-2.0.json

# JSON / SARIF / HTML
abicheck compare libfoo-1.0.json libfoo-2.0.json --format json -o report.json
abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o results.sarif
abicheck compare libfoo-1.0.json libfoo-2.0.json --format html -o report.html
```

### 3) Policy profiles

```bash
# Built-in policy profiles
abicheck compare libfoo-1.0.json libfoo-2.0.json --policy sdk_vendor
abicheck compare libfoo-1.0.json libfoo-2.0.json --policy plugin_abi

# Custom per-kind policy file
abicheck compare libfoo-1.0.json libfoo-2.0.json --policy-file project_policy.yaml

# Suppression file
abicheck compare libfoo-1.0.json libfoo-2.0.json --suppress suppressions.yaml
```

**Policy file example** (`project_policy.yaml`):
```yaml
base_policy: strict_abi
overrides:
  enum_member_renamed: ignore   # break | warn | ignore
  field_renamed: ignore
```

See [Policy Profiles](docs/policies.md) for full reference.

---

## ABICC drop-in replacement

Existing ABICC pipelines work with a one-line swap:

```bash
# Before:
abi-compliance-checker -lib libdnnl -old old.xml -new new.xml -report-path r.html

# After (identical flags):
abicheck compat -lib libdnnl -old old.xml -new new.xml -report-path r.html
```

Migration path:

1. Keep your existing XML descriptor generation.
2. Replace the ABICC CLI call with `abicheck compat`.
3. Move to `dump` + `compare` when you want explicit snapshot control and richer outputs.

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

Exit codes for CI gates: `0` = compatible/no_change, `2` = API break, `4` = breaking ABI change.
See [Exit Codes](docs/exit_codes.md) for full reference including `compat` mode.

---

## Benchmark results

abicheck achieves **100% accuracy** across 48 example cases covering all major ABI break
categories (symbol removal, struct layout, vtable drift, enum changes, calling convention, etc.):

| Tool | Correct / Scored | Accuracy |
|------|-----------------|----------|
| **abicheck (compare)** | **48/48** | **100%** |
| abicheck (compat) | 46/48 | 96% |
| ABICC (xml) | 30/47 | 63% |
| ABICC (abi-dumper) | 24/48 | 50% |
| abidiff | 12/48 | 25% |

See [Benchmark report](docs/benchmark_report.md) and [Tool comparison](docs/tool_comparison.md)
for per-case analysis, timing data, and methodology.

---

## Documentation

- **[Getting started](docs/getting_started.md)** — installation, first check, CI setup
- **[Verdicts](docs/concepts/verdicts.md)** — BREAKING / API_BREAK / COMPATIBLE / NO_CHANGE
- **[Exit Codes](docs/exit_codes.md)** — CI-ready exit code reference
- **[Policy Profiles](docs/policies.md)** — built-in and custom policies
- **[ABICC Migration](docs/migration/from_abicc.md)** — migrating from abi-compliance-checker
- **[ABI Break Catalog](docs/abi_breaking_cases_catalog.md)** — 48 documented break scenarios
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
