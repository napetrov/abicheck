# Migrating from ABICC

This guide helps you move from `abi-compliance-checker` (ABICC) to `abicheck` with minimal disruption.

---

## Step 1: Swap the command

Replace the ABICC binary call with `abicheck compat check`. Keep your existing XML descriptors — no changes needed:

```bash
# Before (ABICC):
abi-compliance-checker -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

```bash
# After (abicheck — same flags):
abicheck compat check -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

All ABICC single-hyphen flags (`-lib`, `-old`, `-new`, `-s`, `-source`, `-binary`, `-v1`, `-v2`, etc.) are supported. See [ABICC Compatibility Reference](../abicc_compat.md) for the full flag list.

---

## Step 2: Update CI exit code checks

Exit codes between ABICC and abicheck compat are similar but not identical:

| Exit code | ABICC | abicheck compat |
|-----------|-------|-----------------|
| `0` | Compatible | Compatible / no change |
| `1` | Breaking | BREAKING |
| `2` | Error | API_BREAK or tool error |

> **Important:** In compat mode, exit `2` can mean either API_BREAK **or** a tool error
> (e.g. missing descriptor file). Pre-validate that your XML descriptor files exist
> before running to avoid ambiguity.

If you later switch to `abicheck compare` (recommended), exit codes change:

| Exit code | abicheck compare |
|-----------|-----------------|
| `0` | NO_CHANGE or COMPATIBLE |
| `1` | Tool error |
| `2` | API_BREAK |
| `4` | BREAKING |

---

## Step 3: Validate on historical releases

Run abicheck on 3-5 known releases and compare results against your existing ABICC outputs:

```bash
for ver in v1.0 v1.1 v1.2; do
  abicheck compat check -lib libfoo -old ${ver}.xml -new current.xml \
    -report-path report-${ver}.html
  echo "vs ${ver}: exit $?"
done
```

---

## Step 4 (optional): Migrate to native mode

When ready, switch from XML descriptors to the simpler native workflow:

```bash
# One-liner compare
abicheck compare libfoo.so.1 libfoo.so.2 -H include/foo.h
```

```bash
# Or: snapshot-based CI workflow
abicheck dump libfoo.so -H include/foo.h --version 1.0 -o baseline.json
abicheck compare baseline.json ./build/libfoo.so --new-header include/foo.h
```

Benefits of native mode:
- Unambiguous `API_BREAK` verdict (not conflated with errors)
- JSON / SARIF output for GitHub Code Scanning
- Simpler CLI — no XML descriptors needed
- Exit code `4` = BREAKING (separate from tool errors)

---

## Jenkins / CI example

```bash
# Pre-validate inputs
if [ ! -f OLD.xml ] || [ ! -f NEW.xml ]; then
  echo "ERROR: descriptor files missing"
  exit 1
fi
```

```bash
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
