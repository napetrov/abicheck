# SARIF Output

abicheck supports [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/) output for integration with GitHub Code Scanning and other SAST platforms.

## Usage

```bash
abicheck compare old.json new.json --format sarif -o results.sarif
```

## GitHub Code Scanning integration

```yaml
# .github/workflows/abi-check.yml
name: ABI Check

on: [pull_request]

jobs:
  abi-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install abicheck
        run: |
          # conda-forge (recommended — includes castxml):
          # conda install -c conda-forge abicheck
          # or via pip (requires castxml installed separately):
          pip install abicheck

      - name: Dump ABI (baseline)
        run: |
          abicheck dump lib/libfoo.so.1 -H include/foo.h \
            --version ${{ github.base_ref }} -o old.json

      - name: Dump ABI (PR)
        run: |
          abicheck dump lib/libfoo.so.2 -H include/foo.h \
            --version ${{ github.head_ref }} -o new.json

      - name: Compare ABI
        run: |
          abicheck compare old.json new.json --format sarif -o abi.sarif
        continue-on-error: true

      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: abi.sarif
```

## Severity mapping

| ABI Change | SARIF Level |
|-----------|-------------|
| Function/variable removed | `error` |
| Type size/layout changed | `error` |
| Return/parameter type changed | `error` |
| Function/variable added | `warning` |

## SARIF document structure

```json
{
  "$schema": "https://raw.githubusercontent.com/.../sarif-schema-2.1.0.json",
  "version": "2.1.0",
  "runs": [{
    "tool": { "driver": { "name": "abicheck", "rules": [...] } },
    "results": [{
      "ruleId": "func_removed",
      "level": "error",
      "message": { "text": "Function foo() removed" },
      "locations": [{
        "physicalLocation": { "artifactLocation": { "uri": "libfoo.so.1" } },
        "logicalLocations": [{ "name": "_Z3foov" }]
      }]
    }]
  }]
}
```
