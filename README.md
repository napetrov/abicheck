# abicheck

[![CI](https://github.com/napetrov/abicheck/actions/workflows/ci.yml/badge.svg)](https://github.com/napetrov/abicheck/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/napetrov/abicheck/branch/main/graph/badge.svg)](https://codecov.io/gh/napetrov/abicheck)

**abicheck checks C/C++ library compatibility at both API and ABI levels.**

abicheck is inspired by two foundational projects:

- [libabigail / abidiff](https://sourceware.org/libabigail/)
- [ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/)

Kudos and many thanks to both communities for building the ABI compatibility ecosystem.

It is designed to be a practical drop-in replacement for
[ABI Compliance Checker (ABICC)](https://lvc.github.io/abi-compliance-checker/),
with modern CLI ergonomics and machine-readable outputs (`json`/`sarif`).

Note: ABICC is currently not actively maintained for many modern workflows,
which is a key reason abicheck exists.

## Requirements

You need all of the following:

- Python 3.10+
- `castxml` (system package; not installed from Python package metadata)
- C/C++ compiler for castxml (`g++` or `clang++`)
- Python runtime deps (installed automatically from package metadata):
  - `click`
  - `pyelftools`
  - `defusedxml`
  - `pyyaml`
  - `google-re2`
  - `packaging`

If `castxml` is missing, install it via your OS package manager (see [docs/getting_started.md](docs/getting_started.md)).

## Installation

PyPI package publishing is planned, but not yet available.

```bash
# coming later
pip install abicheck
```

For local development from this repository:

```bash
pip install -e .
```

## Quick start

### Can I compare in one command?

- **Native mode (`dump` + `compare`)**: currently requires two snapshot files, then one compare command.
- **Single-command flow exists via `compat`** when you already have ABICC XML descriptors (`-old` / `-new`).

### 1) Create ABI snapshots

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o libfoo-2.0.json
```

### 2) Compare snapshots

```bash
# Markdown report (default)
abicheck compare libfoo-1.0.json libfoo-2.0.json

# JSON report
abicheck compare libfoo-1.0.json libfoo-2.0.json --format json -o report.json

# SARIF report
abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o report.sarif
```

### 3) ABICC-compatible mode (`compat`)

```bash
# ABICC-style invocation
abicheck compat -lib foo -old old.xml -new new.xml

# Strict mode and explicit versions
abicheck compat -lib foo -old old.xml -new new.xml -s -v1 1.0 -v2 2.0
```

See [ABICC compatibility reference](docs/abicc_compat.md) for the full flag list and behavior notes.

## Verdicts and CI behavior

`abicheck compare` returns one of four **final verdicts**:

- `NO_CHANGE`
- `COMPATIBLE`
- `API_BREAK`
- `BREAKING`

Additionally, some internal checks can be marked as **review-needed** severity
(at change level / policy level) when evidence is uncertain. This is separate from the
final top-level compare verdict and is primarily used in policy workflows.

For exact exit code semantics and CI gate patterns, use:

- [docs/exit_codes.md](docs/exit_codes.md)
- [docs/concepts/verdicts.md](docs/concepts/verdicts.md)

## Documentation map

- [Docs home](docs/index.md)
- [Getting started](docs/getting_started.md)
- [Usage and coverage model](docs/usage_and_coverage.md)
- [Migration from ABICC](docs/migration/from_abicc.md)
- [ABICC compatibility flags](docs/abicc_compat.md)
- [Tool comparison (interpretation)](docs/tool_comparison.md)
- [Benchmark report (numbers + methodology)](docs/benchmark_report.md)
- [Architecture reference](docs/reference/architecture.md)

## Testing

```bash
# Fast tests (CI-style)
pytest tests/ -v --tb=short -m "not integration and not libabigail" \
  --cov=abicheck --cov-report=term-missing --cov-report=xml --cov-fail-under=52

# Full local suite (when optional external tools are available)
pytest --cov=abicheck --cov-report=term-missing
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
