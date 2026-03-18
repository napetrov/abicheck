# Output Formats

abicheck supports multiple output formats for different use cases:

| Format | Flag | Best for |
|--------|------|----------|
| Markdown | `--format markdown` (default) | Human review, PRs, terminals |
| JSON | `--format json` | CI pipelines, machine processing |
| SARIF | `--format sarif` | GitHub Code Scanning, SAST platforms |
| HTML | `--format html` | Standalone reports, ABICC migration |

All formats support the report filtering options described below.

## Redundancy filtering

When a root type change (e.g. struct size change) causes many derived changes
(e.g. 30 `FUNC_PARAMS_CHANGED` entries for functions using that struct),
abicheck automatically collapses the derived changes. The root type change is
annotated with:

- `caused_count` — number of derived changes collapsed
- `affected_symbols` — list of affected interface names

This keeps reports focused on root causes. Use `--show-redundant` to disable
filtering and see all changes.

### How it appears in each format

**Markdown**: An info note at the bottom:
```
> ℹ️ 12 redundant change(s) hidden (derived from root type changes).
> Use `--show-redundant` to show all.
```

**JSON**: A top-level `redundant_count` field, and per-change `caused_by_type`
and `caused_count` annotations on root type changes.

**SARIF**: `caused_by_type` and `caused_count` in result `properties`;
`redundant_count` in run-level properties.

**HTML**: A highlighted banner showing the redundant count.

**XML (ABICC compat)**: `<redundant_changes>` element in `<problem_summary>`,
`<caused_by>` and `<caused_count>` elements on individual problems. Both binary
and source sections include their own redundant counts.

## `--show-only` filter

Limit displayed changes by severity, element, or action (AND across dimensions,
OR within each). Does not affect the verdict or exit codes.

```bash
abicheck compare old.json new.json --show-only breaking,functions,removed
```

**Markdown / JSON / HTML**: Changes are filtered before rendering. A note shows
how many changes matched: `> Filtered by: --show-only ... (5 of 42 changes shown)`.

**SARIF**: The `show_only` parameter filters which results appear in the SARIF
output.

## `--stat` mode

One-line summary for CI gates:

```bash
$ abicheck compare old.json new.json --stat
BREAKING: 3 breaking, 1 risk (42 total) [12 redundant hidden]

$ abicheck compare old.json new.json --stat --format json
{"library": "libfoo", "verdict": "BREAKING", "summary": {...}}
```

## `--report-mode leaf`

Groups output by root type changes with affected interface lists, instead of
listing every change individually. Available in Markdown and JSON formats.

```bash
abicheck compare old.json new.json --report-mode leaf
```

## `--show-impact`

Appends an impact summary table to the report, showing root changes and how many
interfaces each affects. Available in Markdown and HTML formats.

```bash
abicheck compare old.json new.json --show-impact
```

---

## SARIF Output

abicheck supports [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/) output for integration with GitHub Code Scanning and other SAST platforms.

### Usage

```bash
abicheck compare old.json new.json --format sarif -o results.sarif
```

### GitHub Code Scanning integration

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
          sudo apt-get update && sudo apt-get install -y castxml g++
          pip install abicheck  # TODO: not yet published to PyPI — install from source for now

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

### Severity mapping

| ABI Change | SARIF Level |
|-----------|-------------|
| Function/variable removed | `error` |
| Type size/layout changed | `error` |
| Return/parameter type changed | `error` |
| Function/variable added | `warning` |

### SARIF document structure

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
      }],
      "properties": {
        "caused_by_type": null,
        "caused_count": 0
      }
    }]
  }]
}
```
