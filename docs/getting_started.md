# Getting Started

**abicheck** compares two versions of a C/C++ shared library and tells you whether existing binaries will break. It analyses ELF symbols, C/C++ header AST (via castxml), and DWARF debug info to catch ABI incompatibilities that other tools miss.

> **Platform:** Linux only (ELF binaries + DWARF + C/C++ headers).

---

## 1) Install abicheck

> **Note:** abicheck is not yet published to PyPI or conda-forge. Install from source.

### Requirements

- Python 3.10+
- `castxml` (Clang-based C/C++ AST parser) — see [castxml project](https://github.com/CastXML/CastXML)
- C/C++ compiler (`gcc`/`g++` or `clang`/`clang++`)

Install castxml on Ubuntu/Debian:

```bash
sudo apt-get update && sudo apt-get install -y castxml gcc g++
```

Or via conda:

```bash
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

The repo includes 48 ABI break examples with paired `v1`/`v2` sources and headers:

```bash
cd examples/case01_symbol_removal
```

```bash
# Build v1 and v2 shared libraries
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so
```

```bash
# Compare
abicheck compare libv1.so libv2.so --old-header v1.h --new-header v2.h
# Verdict: BREAKING (symbol 'helper' was removed)
```

For your own library:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 \
  --old-header include/v1/foo.h --new-header include/v2/foo.h
```

If the header is the same for both versions:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

---

## 3) Output formats

abicheck supports four output formats: `markdown` (default), `json`, `sarif`, `html`.

Markdown (default, printed to stdout):

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H foo.h
```

JSON — machine-readable, includes precise verdict field:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H foo.h --format json -o result.json
```

SARIF — for GitHub Code Scanning:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H foo.h --format sarif -o abi.sarif
```

HTML — standalone human-readable report:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H foo.h --format html -o report.html
```

---

## 4) Snapshot workflow (for CI baselines)

Save a snapshot once per release, then compare against new builds without re-dumping:

```bash
# Save baseline (header is baked into the snapshot)
abicheck dump libfoo.so -H include/foo.h --version 1.0 -o baseline.json
```

```bash
# Compare saved baseline against current build
abicheck compare baseline.json ./build/libfoo.so \
  --new-header include/foo.h --new-version 2.0-dev
```

```bash
# Or compare two snapshots (no headers needed — already baked in)
abicheck compare old.json new.json
```

`compare` auto-detects each input: `.so` files are dumped on-the-fly, `.json` snapshots are loaded directly. You can mix them freely.

### Language mode

Use `--lang c` for pure C libraries (default is `c++`):

```bash
abicheck dump libfoo.so -H foo.h --lang c -o snap.json
```

### Cross-compilation

When analysing libraries built for a different architecture:

```bash
abicheck dump libfoo.so -H include/foo.h \
  --gcc-prefix aarch64-linux-gnu- \
  --sysroot /opt/sysroots/aarch64 \
  -o snap.json
```

Available flags: `--gcc-path`, `--gcc-prefix`, `--gcc-options`, `--sysroot`, `--nostdinc`.

### Verbose output

```bash
abicheck compare old.json new.json -v
```

---

## 5) Exit codes

| Exit code | Verdict | Meaning |
|-----------|---------|---------|
| `0` | `NO_CHANGE` or `COMPATIBLE` | Safe — no breaking changes |
| `1` | — | Tool/runtime error |
| `2` | `API_BREAK` | Source-level break (recompile needed, binary may work) |
| `4` | `BREAKING` | Binary ABI break |

> Exit `0` covers both `NO_CHANGE` and `COMPATIBLE`.
> If you need exact verdicts in CI, parse `--format json` output.

Full reference (including `compat` mode and strict mode): [Exit Codes](exit_codes.md)

---

## 6) Add to GitHub Actions

Typical flow: dump the ABI baseline once at release time, then compare every new build against it.

**Release step** — save the baseline as an artifact:

```bash
abicheck dump ./build/libfoo.so -H include/foo.h \
  --version 1.0 -o abi-baseline.json
# Upload abi-baseline.json as a release artifact
```

**CI step** — compare new build against saved baseline:

```yaml
steps:
  - name: Download ABI baseline
    uses: actions/download-artifact@v4
    with:
      name: abi-baseline

  - name: Compare ABI
    run: |
      abicheck compare abi-baseline.json ./build/libfoo.so \
        --new-header include/foo.h \
        --format sarif -o abi.sarif

  - uses: github/codeql-action/upload-sarif@v3
    if: always()
    with:
      sarif_file: abi.sarif
```

---

## 7) Migrating from ABICC?

If you have existing ABICC XML descriptors, use `compat` mode — same single-hyphen flags, no XML changes needed:

```bash
abicheck compat check -lib foo -old OLD.xml -new NEW.xml
```

When ready, switch to the simpler native workflow:

```bash
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

See [Migrating from ABICC](migration/from_abicc.md) for the full guide.

---

## 8) Next steps

- [Verdicts explained](concepts/verdicts.md)
- [Policy Profiles](policies.md) — control how changes are classified
- [Examples & Breakage Guide](examples_breakage_guide.md) — 48 real-world ABI break scenarios
- [Limitations](concepts/limitations.md)
- [Benchmark & Tool Comparison](tool_comparison.md) — abicheck vs abidiff vs ABICC
