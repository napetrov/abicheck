# Getting Started

This guide gets you from **zero** to a first ABI verdict in ~10–15 minutes.

---

## 1) Requirements

- Python 3.10+
- `castxml`
- C/C++ compiler available to castxml (`g++` or `clang++`)

### Install system dependencies

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
```

For development from source:

```bash
git clone https://github.com/napetrov/abicheck.git
cd abicheck
pip install -e .
```

---

## 3) First check (dump + compare)

Assume:
- old library: `libfoo.so.1`
- new library: `libfoo.so.2`
- public header: `include/foo.h`

```bash
abicheck dump libfoo.so.1 -H include/foo.h --version 1.0 -o foo-1.0.json
abicheck dump libfoo.so.2 -H include/foo.h --version 2.0 -o foo-2.0.json
abicheck compare foo-1.0.json foo-2.0.json
```

You get one verdict:
- `NO_CHANGE`
- `COMPATIBLE`
- `API_BREAK`
- `BREAKING`

---

## 4) Exit codes (important)

`abicheck compare`:
- `0` = `NO_CHANGE` **or** `COMPATIBLE`
- `2` = `API_BREAK`
- `4` = `BREAKING`

> ⚠️ If your CI treats `0` as “nothing changed”, you will miss `COMPATIBLE` changes.
> Parse JSON output if you need exact verdict in automation.

Full details: [Exit Codes](exit_codes.md)

---

## 5) Add to GitHub Actions

```yaml
- name: Compare ABI snapshots
  run: |
    abicheck compare old.json new.json --format sarif -o abi.sarif

- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: abi.sarif
```

---

## 6) Migrating from ABICC?

Use `compat` mode as a drop-in:

```bash
abicheck compat -lib foo -old OLD.xml -new NEW.xml
```

Read: [Migrating from ABICC](migration/from_abicc.md)

---

## 7) Next steps

- [Verdicts](concepts/verdicts.md)
- [Limitations](concepts/limitations.md)
- [Tool comparison](tool_comparison.md)
- [Examples breakage guide](examples_breakage_guide.md)
