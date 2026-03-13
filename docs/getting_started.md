# Getting Started

> ⚠️ **Before you start:** `abicheck compare` exits `0` for both `NO_CHANGE` *and*
> `COMPATIBLE`. Checking `$? -eq 0` does **not** mean "nothing changed" — it means
> "no binary ABI break". See [Exit Codes](exit_codes.md) for CI gate patterns.

---

## 1) Install abicheck

> **Note:** abicheck is not yet published to PyPI or conda-forge. Install from source.

### Requirements

- Python 3.10+
- `castxml` (for header-based analysis) — see [castxml project](https://github.com/CastXML/CastXML)
- C/C++ compiler (`gcc`/`g++` or `clang`/`clang++`)

```bash
# Install castxml
# Ubuntu / Debian
sudo apt-get update && sudo apt-get install -y castxml gcc g++
# or via conda
conda install -c conda-forge castxml
```

### Install from source

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e .
```

---

## 2) First check (using repo examples)

The repo includes a broad set of ABI break examples (C and C++) with paired
`v1`/`v2` sources and headers. This makes it easy to verify your install is
working correctly and to understand typical break patterns.

```bash
# Clone the repo (skip if already done in step 1)
git clone https://github.com/napetrov/abicheck.git
cd abicheck/examples/case01_symbol_removal

# Build v1 and v2 shared libraries
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so

# One-liner: compare directly (each version has its own header)
abicheck compare libv1.so libv2.so --old-header v1.h --new-header v2.h
# Expected output: verdict BREAKING (symbol 'helper' was removed)
```

For your own C++ library:

```bash
# Each version has its own header
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h

# Multiple headers per version
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --old-header include/v1/bar.h \
  --new-header include/v2/foo.h --new-header include/v2/bar.h \
  -I include/

# Shorthand: -H when the same header applies to both versions
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h

# With version labels
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h \
  --old-version 1.0 --new-version 2.0
```

---

## 3) Output formats

```bash
# Default: markdown report to stdout
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header v1/foo.h --new-header v2/foo.h

# JSON — includes precise verdict field for CI parsing
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header v1/foo.h --new-header v2/foo.h --format json -o result.json

# SARIF — for GitHub Code Scanning
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header v1/foo.h --new-header v2/foo.h --format sarif -o abi.sarif

# HTML — human-readable standalone report
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header v1/foo.h --new-header v2/foo.h --format html -o report.html

# Works the same with pre-dumped snapshots
abicheck compare v1.json v2.json --format sarif -o abi.sarif
```

---

## 4) Snapshot workflow (for CI baselines)

When you need reusable baselines (e.g. store as CI artifact, commit to repo):

```bash
# Dump snapshot once per release (header is baked into the snapshot)
abicheck dump libfoo.so.1 -H include/v1/foo.h --version 1.0 -o baseline.json

# In CI: compare saved baseline against current build
abicheck compare baseline.json ./build/libfoo.so \
  --new-header include/foo.h --new-version 2.0-dev

# Or compare two snapshots (no headers needed — already baked in)
abicheck compare old.json new.json
```

---

## 5) Exit codes (`abicheck compare`)

`abicheck compare` uses four statuses:
- `0` → `NO_CHANGE` or `COMPATIBLE`
- `1` → tool/runtime error
- `2` → `API_BREAK`
- `4` → `BREAKING`

> ⚠️ Exit `0` covers both `NO_CHANGE` and `COMPATIBLE`.
> If you need exact verdicts in CI, parse `--format json` output.

Canonical reference (compare + compat + strict mode): [Exit Codes](exit_codes.md)

---

## 6) Add to GitHub Actions

```yaml
steps:
  # One-step ABI check (compare .so files directly)
  - name: Compare ABI
    run: |
      abicheck compare libfoo_old.so libfoo_new.so \
        --old-header include/v1/foo.h --new-header include/v2/foo.h \
        --old-version 1.0 --new-version 2.0 \
        --format sarif -o abi.sarif
      ret=$?
      [ $ret -eq 1 ] && echo "Tool error" && exit 1
      [ $ret -eq 4 ] && echo "BREAKING ABI change — blocked" && exit 1
      [ $ret -eq 2 ] && echo "::warning::API_BREAK detected"
      exit 0

  - uses: github/codeql-action/upload-sarif@v3
    if: always()
    with:
      sarif_file: abi.sarif
```

Or using a saved baseline snapshot:

```yaml
steps:
  - name: ABI check vs baseline
    run: |
      abicheck compare abi-baselines/libfoo-1.0.json ./build/libfoo.so \
        --new-header include/foo.h --new-version ${{ github.sha }} \
        --format sarif -o abi.sarif
```

---

## 7) Migrating from ABICC?

If you have existing ABICC XML descriptors, use `compat` mode — same single-hyphen flags,
no XML changes needed:

```bash
# Direct drop-in
abicheck compat check -lib foo -old OLD.xml -new NEW.xml

# OLD.xml is the same ABICC descriptor format you already have.
# When ready to simplify, switch to:
#   abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

Read: [Migrating from ABICC](migration/from_abicc.md)

---

## 8) Next steps

- [Verdicts explained](concepts/verdicts.md)
- [Limitations & known boundaries](concepts/limitations.md)
- [Tool comparison: abicheck vs abidiff vs ABICC](tool_comparison.md)
- [Examples breakage guide](examples_breakage_guide.md)
