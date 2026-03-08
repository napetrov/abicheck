# Getting Started

## Requirements

- Python 3.10+
- `castxml` (required for header-based API/ABI parsing)
- C/C++ toolchain (`g++` or `clang++`) for realistic header parsing context

Optional but useful:

- `abidiff` (libabigail) for side-by-side comparisons
- ABICC/abi-dumper tools for legacy pipeline migration and parity checks

## Installation

```bash
pip install abicheck
```

System dependencies:

```bash
# Ubuntu/Debian
sudo apt-get install castxml

# macOS
brew install castxml
```

## Quick workflow

### 1. Dump ABI snapshots

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o libfoo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o libfoo-2.0.json
```

### 2. Compare snapshots

```bash
# Markdown report (default)
abicheck compare libfoo-1.0.json libfoo-2.0.json

# JSON report
abicheck compare libfoo-1.0.json libfoo-2.0.json --format json -o results.json

# SARIF report (GitHub Code Scanning)
abicheck compare libfoo-1.0.json libfoo-2.0.json --format sarif -o results.sarif
```

### 3. ABICC-compatible mode (drop-in migration)

```bash
abicheck compat -lib foo -old foo-1.0.xml -new foo-2.0.xml
```

For a deeper walkthrough (drop-in ABICC usage, breakage matrix, and architecture),
see [Using abicheck, Compatibility Modes, and Coverage](usage_and_coverage.md).

## Python API

```python
from pathlib import Path
from abicheck.dumper import dump
from abicheck.checker import compare

old = dump(Path("libfoo.so.1"), headers=[Path("include/foo.h")], version="1.0")
new = dump(Path("libfoo.so.2"), headers=[Path("include/foo.h")], version="2.0")

result = compare(old, new)
print(result.verdict)       # NO_CHANGE | COMPATIBLE | BREAKING
print(result.changes)       # list[Change]
```
