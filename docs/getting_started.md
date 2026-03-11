# Getting Started

> ⚠️ **Exit code note before you start:** `abicheck compare` exits `0` for both
> `NO_CHANGE` and `COMPATIBLE`. If you check `$? -eq 0` to detect "no changes",
> you will silently miss compatible changes (new exports, etc.).
> See [Exit Codes](exit_codes.md) for how to handle this in CI.

This guide gets you from **zero** to a first ABI verdict in ~10–15 minutes.

---

## 1) Requirements

- Python 3.10+
- `castxml` (for header-based analysis) — [castxml project](https://github.com/CastXML/CastXML)
- C/C++ compiler available to castxml (`g++` or `clang++`)

### Install system dependencies first

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y castxml g++

# macOS
brew install castxml llvm
```

---

## 2) Install abicheck

```bash
pip install abicheck

# Verify install
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

The repo includes 42 pre-built example cases. Run a quick check on one:

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck/examples/case01_symbol_removal

# Build v1 and v2
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so

# Dump ABI snapshots
abicheck dump libv1.so -H v1.h --version 1.0 -o v1.json
abicheck dump libv2.so -H v2.h --version 2.0 -o v2.json

# Compare
abicheck compare v1.json v2.json
# Expected: BREAKING (symbol removed)
```

For your own library with `libfoo.so.1`, `libfoo.so.2`, `include/foo.h`:

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o foo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o foo-2.0.json
abicheck compare foo-1.0.json foo-2.0.json
```

---

## 4) Understanding output formats

```bash
# Default: markdown report to stdout
abicheck compare foo-1.0.json foo-2.0.json

# JSON (machine-readable, includes precise verdict)
abicheck compare foo-1.0.json foo-2.0.json --format json -o result.json

# SARIF (GitHub Code Scanning)
abicheck compare foo-1.0.json foo-2.0.json --format sarif -o abi.sarif
```

---

## 5) Exit codes

`abicheck compare`:
- `0` = `NO_CHANGE` **or** `COMPATIBLE`
- `1` = tool error (check inputs)
- `2` = `API_BREAK`
- `4` = `BREAKING`

Full details and CI gate templates: [Exit Codes](exit_codes.md)

---

## 6) Add to GitHub Actions

```yaml
- name: Compare ABI snapshots
  run: |
    abicheck compare old.json new.json --format sarif -o abi.sarif
    ret=$?
    # Handle exit codes explicitly
    if [ $ret -eq 4 ]; then echo "BREAKING ABI change"; exit 1; fi
    if [ $ret -eq 2 ]; then echo "API_BREAK"; exit 1; fi

- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: abi.sarif
```

---

## 7) Migrating from ABICC?

Use `compat` mode as a drop-in (same single-hyphen flags):

```bash
abicheck compat -lib foo -old OLD.xml -new NEW.xml
```

Read: [Migrating from ABICC](migration/from_abicc.md)

---

## 8) Next steps

- [Verdicts explained](concepts/verdicts.md)
- [Limitations & known boundaries](concepts/limitations.md)
- [Tool comparison: abicheck vs abidiff vs ABICC](tool_comparison.md)
- [Examples breakage guide](examples_breakage_guide.md)
