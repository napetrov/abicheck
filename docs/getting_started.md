# Getting Started

> ⚠️ **Before you start:** `abicheck compare` exits `0` for both `NO_CHANGE` *and*
> `COMPATIBLE`. Checking `$? -eq 0` does **not** mean "nothing changed" — it means
> "no binary ABI break". See [Exit Codes](exit_codes.md) for CI gate patterns.

---

## 1) Requirements

- Python 3.10+
- `castxml` (for header-based analysis) — [castxml project](https://github.com/CastXML/CastXML)
- C/C++ compiler (`gcc`/`g++` or `clang`/`clang++`)

### Install system dependencies first

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y castxml gcc g++

# macOS (development only — ELF analysis requires Linux)
# abicheck analyzes Linux ELF binaries only; macOS Mach-O is not supported.
# castxml can be installed for Tier 1 header-parsing development,
# but Tier 2/3/4 ELF analysis requires a Linux environment.
brew install castxml llvm
```

---

## 2) Install abicheck

```bash
# Recommended: use a virtual environment
python3 -m venv .venv && source .venv/bin/activate

pip install abicheck

# Verify
abicheck --version
```

For development from source:

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e .
```

---

## 3) First check (using repo examples)

The repo includes a broad set of ABI break examples (C and C++) with paired
`v1`/`v2` sources and headers. This makes it easy to verify your install is
working correctly and to understand typical break patterns.

```bash
# Clone the repo (skip if already done in step 2)
git clone https://github.com/napetrov/abicheck.git
cd abicheck/examples/case01_symbol_removal

# Build v1 and v2 shared libraries
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so

# Dump ABI snapshots (v1.h and v2.h are in the same directory)
abicheck dump libv1.so -H v1.h --version 1.0 -o v1.json
abicheck dump libv2.so -H v2.h --version 2.0 -o v2.json

# Compare
abicheck compare v1.json v2.json
# Expected output: verdict BREAKING (symbol 'helper' was removed)
```

For your own C++ library:

```bash
# Replace with your actual paths
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o foo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o foo-2.0.json
abicheck compare foo-1.0.json foo-2.0.json
```

---

## 4) Output formats

```bash
# Default: markdown report to stdout
abicheck compare v1.json v2.json

# JSON — includes precise verdict field for CI parsing
abicheck compare v1.json v2.json --format json -o result.json

# SARIF — for GitHub Code Scanning
abicheck compare v1.json v2.json --format sarif -o abi.sarif
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
  # Step 1: Generate baseline snapshot (typically from previous release tag)
  - name: Dump old ABI snapshot
    run: abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o old.json

  # Step 2: Dump new snapshot (from current build)
  - name: Dump new ABI snapshot
    run: abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o new.json

  # Step 3: Compare and generate SARIF
  - name: Compare ABI
    run: |
      abicheck compare old.json new.json --format sarif -o abi.sarif
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

---

## 7) Migrating from ABICC?

If you have existing ABICC XML descriptors, use `compat` mode — same single-hyphen flags,
no XML changes needed:

```bash
# Direct drop-in
abicheck compat -lib foo -old OLD.xml -new NEW.xml

# OLD.xml is the same ABICC descriptor format you already have.
# If you don't have XML descriptors yet, use abicheck dump to generate snapshots
# and then abicheck compare instead.
```

Read: [Migrating from ABICC](migration/from_abicc.md)

---

## 8) Next steps

- [Verdicts explained](concepts/verdicts.md)
- [Limitations & known boundaries](concepts/limitations.md)
- [Tool comparison: abicheck vs abidiff vs ABICC](tool_comparison.md)
- [Examples breakage guide](examples_breakage_guide.md)
