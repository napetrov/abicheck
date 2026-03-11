# Migrating from ABI Compliance Checker (ABICC)

`abicheck compat` is designed as a practical drop-in path for ABICC pipelines.
Flags use single-hyphen style (`-lib`, `-old`, `-new`) to match ABICC exactly.

---

## 1) One-line swap

Before:

```bash
abi-compliance-checker -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

After (identical flags):

```bash
abicheck compat -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

---

## 2) Exit codes (critical difference)

> ⚠️ If you switch to `abicheck compare` (not `compat`), exit codes differ — update CI logic.

| Tool / mode | 0 | 1 | 2 | 4 |
|-------------|---|---|---|---|
| ABICC | ok | breaking | error | — |
| `abicheck compat` | ok | breaking | API_BREAK **or** error | — |
| `abicheck compare` | NO_CHANGE or COMPATIBLE | error | API_BREAK | BREAKING |

Note: In `compat` mode, exit `2` conflates `API_BREAK` with tool errors. Pre-validate
that your XML descriptor files exist before relying on exit `2` as an API_BREAK signal.

---

## 3) Supported ABICC flags

Core flags — fully supported:

| Flag | Aliases | Description |
|------|---------|-------------|
| `-lib NAME` | `-l`, `-library` | Library name |
| `-old PATH` | `-d1` | Old version descriptor or dump |
| `-new PATH` | `-d2` | New version descriptor or dump |
| `-report-path PATH` | | Output report path |
| `-report-format FMT` | | `html` (default), `json`, `md` |
| `-s` | `-strict` | Strict mode: COMPATIBLE → BREAKING |
| `-source` | `-src`, `-api` | Source/API compat only |
| `-binary` | `-bin`, `-abi` | Binary ABI mode (default) |
| `-show-retval` | | Include return-value changes |
| `-v1 NUM` | `-vnum1` | Override old version label |
| `-v2 NUM` | `-vnum2` | Override new version label |
| `-skip-symbols PATH` | | Suppress listed symbols |
| `-skip-types PATH` | | Suppress listed types |
| `-stdout` | | Print report to stdout |

Not supported (ABICC-only features):
- `-xml` / `-dump` / `-dump-path` — ABICC's ABI dump generation; use `abicheck dump` instead
- `-headers-only` — reserved, not yet implemented
- `-cross-gcc` — cross-compilation checks not yet implemented
- `-relpath` — relative paths in reports

---

## 4) Migration checklist

1. Replace ABICC binary call with `abicheck compat` (keep XML descriptors unchanged)
2. Validate exit code behavior in CI (especially exit `2` semantics)
3. Run on 3–5 historical releases to establish confidence
4. Optionally migrate to `abicheck compare` for `API_BREAK` verdict and JSON/SARIF workflows

---

## 5) Jenkins stage example

```bash
# Pre-validate inputs to avoid exit-2 ambiguity
[ ! -f OLD.xml ] || [ ! -f NEW.xml ] && echo "ERROR: descriptor files missing" && exit 1

abicheck compat -lib libfoo -old OLD.xml -new NEW.xml \
  -report-format html -report-path abi-report.html
ret=$?

if [ $ret -eq 1 ]; then
  echo "BREAKING ABI change — build blocked"
  exit 1
fi
if [ $ret -eq 2 ]; then
  echo "API_BREAK or tool error — investigate abi-report.html"
  exit 1
fi
echo "ABI check passed"
```

---

## 6) When to move beyond `compat`

Use `abicheck compare` if you need:
- `API_BREAK` as an explicit, unambiguous verdict (not conflated with errors)
- JSON / SARIF-first automation (GitHub Code Scanning, dashboards)
- Direct snapshot workflow (`abicheck dump` → `abicheck compare`)
