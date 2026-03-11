# Migrating from ABI Compliance Checker (ABICC)

`abicheck compat` is designed as a practical drop-in path for ABICC pipelines.

---

## 1) One-line swap

Before:

```bash
abi-compliance-checker -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

After:

```bash
abicheck compat -lib libfoo -old OLD.xml -new NEW.xml -report-path report.html
```

---

## 2) Exit codes (critical difference)

| Tool / mode | 0 | 1 | 2 | 4 |
|-------------|---|---|---|---|
| ABICC | ok | breaking | error | - |
| `abicheck compat` | ok | breaking | API_BREAK or error | - |
| `abicheck compare` | NO_CHANGE or COMPATIBLE | error | API_BREAK | BREAKING |

> ⚠️ If you migrate from ABICC to `abicheck compare` (not `compat`), update CI logic.

---

## 3) Flag compatibility

Core flags preserved:

- `-lib`
- `-old` / `-new`
- `-report-path`
- `-report-format`
- `-s` / `-strict`
- `-source` / `-binary`
- `-show-retval`
- `-v1` / `-v2`
- `-skip-symbols` / `-skip-types`

Full list: [ABICC compatibility reference](../abicc_compat.md)

---

## 4) Migration checklist

1. Replace ABICC binary call with `abicheck compat`
2. Keep existing XML descriptors unchanged
3. Validate exit code behavior in CI
4. Compare 3–5 historical releases to establish confidence
5. Optionally migrate to `abicheck compare` for full `API_BREAK` fidelity and JSON/SARIF workflows

---

## 5) Jenkins stage example

```bash
abicheck compat -lib libfoo -old OLD.xml -new NEW.xml -report-format html -report-path abi-report.html
ret=$?
if [ $ret -eq 1 ]; then
  echo "BREAKING ABI change"
  exit 1
fi
if [ $ret -eq 2 ]; then
  echo "API_BREAK or execution error"
  exit 1
fi
```

---

## 6) When to leave `compat`

Use `abicheck compare` if you need:
- `API_BREAK` as explicit verdict in CI
- JSON / SARIF-first automation
- direct snapshot workflow (`dump` → `compare`)

