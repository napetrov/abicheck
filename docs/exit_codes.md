# Exit Codes

`abicheck` uses different exit codes for `compare` and `compat` commands.

**Why they differ:** `compare` is the native interface with a wider exit code range (0/1/2/4) that distinguishes tool errors from API breaks from binary breaks. `compat` mirrors `abi-compliance-checker` exit codes (0/1/2) so existing ABICC CI scripts work without changes.

---

## `abicheck compare`

| Exit code | Meaning |
|-----------|---------|
| `0` | `NO_CHANGE`, `COMPATIBLE`, or `COMPATIBLE_WITH_RISK` — no binary ABI break |
| `1` | `ADDITIONS` — new public symbols/types detected (only with `--fail-on-additions`) |
| `2` | `API_BREAK` — source-level API break — recompilation required |
| `4` | `BREAKING` — binary ABI break |

> **⚠️ Exit `0` covers `NO_CHANGE`, `COMPATIBLE`, and `COMPATIBLE_WITH_RISK`.** If your pipeline needs
> to distinguish them (e.g. warn on deployment risk), use `--format json` and
> read the `verdict` field — exit code alone is not sufficient.

> **ℹ️ Exit `1` (ADDITIONS)** is only produced when `--fail-on-additions` is passed.
> Without that flag, API additions are reported as `COMPATIBLE` with exit code `0`.

### CI gate patterns

```bash
# Production gate: fail on any break
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && echo "ERROR — check tool inputs" && exit 1    # tool error
[ $ret -eq 4 ] && echo "BREAKING — release blocked" && exit 1
[ $ret -eq 2 ] && echo "API_BREAK — source-level break" && exit 1
echo "OK (NO_CHANGE or COMPATIBLE)"

# Permissive gate: fail only on binary breaks (allow API_BREAK + COMPATIBLE)
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && exit 1   # tool error
[ $ret -eq 4 ] && exit 1   # BREAKING only; API_BREAK (exit 2) allowed
exit 0
# note: exit 0 includes both NO_CHANGE and COMPATIBLE

# Parse exact verdict from JSON
abicheck compare old.json new.json --format json -o result.json
verdict=$(python3 -c "import json,sys; d=json.load(open('result.json')); print(d['verdict'])" \
  || { echo "ERROR parsing result.json"; exit 1; })
[ "$verdict" = "BREAKING" ] && exit 1
```

---

## `abicheck compat`

Matches `abi-compliance-checker` exit codes (ABICC drop-in):

| Exit code | Meaning |
|-----------|---------|
| `0` | No breaking changes (`NO_CHANGE` or `COMPATIBLE`) |
| `1` | `BREAKING` (mirrors ABICC) |
| `2` | `API_BREAK` (source-level break; non-verdict failures use extended codes below) |

> Non-verdict/tool failures are classified via **Extended compat error codes (ABICC-style)** below (`3`, `4`, `5`, `6`, `7`, `8`, `10`, `11`).

---


### Extended compat error codes (ABICC-style)

In `abicheck compat`, non-verdict failures are further classified where possible:

| Exit code | Typical cause |
|-----------|---------------|
| `3` | Required external command/tool is missing (for example `castxml`) |
| `4` | Cannot access input files (missing or permission denied) |
| `5` | Header compile/parsing failure during dump |
| `6` | Invalid compat configuration/input (descriptor, suppression, regex flags) |
| `7` | Failed to write report/output artifact |
| `8` | Dump/analysis pipeline failure |
| `10` | Generic internal/tool failure fallback |
| `11` | Interrupted run |

> Note: classification is best-effort and context-dependent; `API_BREAK` remains `2`.

## Summary table

| Verdict / State | `compare` exit | `compat` exit |
|-----------------|---------------|---------------|
| `NO_CHANGE` | `0` | `0` |
| `COMPATIBLE` | `0` | `0` |
| `COMPATIBLE_WITH_RISK` | `0` | `0` |
| `API_BREAK` | `2` | `2` |
| `BREAKING` | `4` | `1` |
| Tool error | `1` | `3/4/5/6/7/8/10/11` |

---

## Strict mode (`-s` / `-strict`)

`compat` (and only `compat`) supports strict mode to promote lesser verdicts:

```bash
# Strict mode: COMPATIBLE + API_BREAK → exit 1 (BREAKING)
abicheck compat -lib foo -old OLD.xml -new NEW.xml -s

# Strict API-only: only API_BREAK → exit 1; COMPATIBLE stays exit 0
abicheck compat -lib foo -old OLD.xml -new NEW.xml -s --strict-mode api
```

`--strict-mode` values:
- `full` (default when `-s` is set): `COMPATIBLE` + `API_BREAK` → BREAKING
- `api`: only `API_BREAK` → BREAKING; `COMPATIBLE` unchanged

`--strict-mode` has no effect unless `-s` is also passed.

> Note: `abicheck compare` does not have `-s` / `--strict` flags.
> For compare-mode strict pipelines, use CI exit code logic (check exit `2` as a failure).
