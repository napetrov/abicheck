# Migrating from ABI Compliance Checker (ABICC)

`abicheck compat check` is designed as a practical drop-in path for ABICC pipelines.
Flags use single-hyphen style (`-lib`, `-old`, `-new`) to match ABICC exactly.

---

## 1) One-line swap

Before:

```bash
abi-compliance-checker -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

After (identical flags):

```bash
abicheck compat check -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

> `OLD.xml` is your existing ABICC XML descriptor file in most pipelines.
> If your ABICC setup emits XML *fragments* (sibling `<version>`, `<headers>`,
> `<libs>` tags without a single wrapper root), add a one-time normalization
> step to wrap them in a root element (for example `<descriptor>...</descriptor>`).
> If you don't have XML descriptors yet, use `abicheck dump` to generate snapshots
> and then `abicheck compare` instead.

---

## 2) Exit codes (critical difference)

> ⚠️ If you switch to `abicheck compare` (not `compat`), exit codes differ — update CI logic.

| Tool / mode | 0 | 1 | 2 | 4 |
|-------------|---|---|---|---|
| ABICC | ok | breaking | error | — |
| `abicheck compat check` | ok | BREAKING | API_BREAK or tool error | — |
| `abicheck compare` | NO_CHANGE or COMPATIBLE | tool error | API_BREAK | BREAKING |

> ⚠️ In `compat` mode, exit `1` = BREAKING (mirrors ABICC). Exit `2` = API_BREAK
> **or** tool error (descriptor parse failure, missing `.so`). Pre-validate that your
> XML descriptor files exist before running — a missing file exits `2`, same as
> API_BREAK. To disambiguate, use `--format json` and check the `verdict` field
> (a tool error will produce no `changes` in the JSON output).

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
| `-s` | `-strict` | Strict mode: COMPATIBLE + API_BREAK → exit 1 |
| `-source` | `-src`, `-api` | Source/API compat only |
| `-binary` | `-bin`, `-abi` | Binary ABI mode (default) |
| `-show-retval` | | Include return-value changes |
| `-v1 NUM` | `-vnum1` | Override old version label |
| `-v2 NUM` | `-vnum2` | Override new version label |
| `-skip-symbols PATH` | | Suppress listed symbols |
| `-skip-types PATH` | | Suppress listed types |
| `-stdout` | | Print report to stdout |
| `-warn-newsym` | | Treat new exported symbols as a break (exit 2) |
| `-relpath PATH` | | Base path for relative paths in reports |

Cross-compilation and advanced flags — also supported:

| Flag | Description |
|------|-------------|
| `-gcc-path PATH` | Custom GCC/G++ path (passed to castxml) |
| `-gcc-prefix PREFIX` | Cross-toolchain prefix, e.g. `aarch64-linux-gnu-` |
| `-gcc-options FLAGS` | Extra compiler flags for castxml |
| `-sysroot PATH` | Alternative sysroot |
| `-nostdinc` | Skip standard include paths |
| `-lang C\|C++` | Force language mode |
| `-relpath1`/`-relpath2` | Per-side relpath substitution |
| `-headers-only` | Accepted (ELF checks still run) |
| `-v1num`/`-v2num` | ABICC 1.x version aliases → mapped to `-v1`/`-v2` |

Dump workflow — supported via `abicheck compat dump`:

```bash
# Create an ABI dump from an ABICC XML descriptor:
abicheck compat dump -lib libfoo -dump v1.xml
abicheck compat dump -lib libfoo -dump v2.xml
abicheck compat check -lib libfoo -old abi_dumps/libfoo/1.0/dump.json -new abi_dumps/libfoo/2.0/dump.json
```

See [abicc_compat.md](../abicc_compat.md) for the full flag reference.

---

## 4) Migration checklist

1. Replace ABICC binary call with `abicheck compat check` (keep XML descriptors unchanged)
2. Validate exit code behavior in CI — especially: compat exit `1` = BREAKING, exit `2` = API_BREAK or error
3. Run on 3–5 historical releases to establish confidence, e.g.:
   ```bash
   for ver in v1.0 v1.1 v1.2; do
     abicheck compat check -lib libfoo -old ${ver}.xml -new current.xml \
       -report-path report-${ver}.html
     echo "vs ${ver}: exit $?"
   done
   ```
4. Optionally migrate to `abicheck compare` for unambiguous `API_BREAK` verdict and JSON/SARIF workflows

> **Migration note (v0.2):** `abicheck compat -lib ...` was renamed to `abicheck compat check -lib ...`.
> `abicheck compat-dump ...` was renamed to `abicheck compat dump ...`.

---

## 5) Jenkins stage example

```bash
# Pre-validate inputs to avoid exit-2 ambiguity (missing file → exit 2 = same as API_BREAK)
if [ ! -f OLD.xml ] || [ ! -f NEW.xml ]; then
  echo "ERROR: descriptor files missing"
  exit 1
fi

abicheck compat check -lib libfoo -old OLD.xml -new NEW.xml \
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
