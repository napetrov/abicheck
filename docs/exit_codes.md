# Exit Codes

`abicheck` uses different exit codes depending on the command (`compare` vs `compat`).

---

## `abicheck compare`

| Exit code | Meaning |
|-----------|---------|
| `0` | `NO_CHANGE` **or** `COMPATIBLE` — no binary ABI break detected |
| `1` | Error — missing input, invalid snapshot, or tool failure |
| `2` | `API_BREAK` — source-level break (compile-time only; existing binaries are safe) |
| `4` | `BREAKING` — binary ABI break; existing consumers will malfunction |

> **⚠️ Important:** Exit code `0` means **either** `NO_CHANGE` or `COMPATIBLE`.
> If your pipeline should **warn** on `COMPATIBLE` changes (e.g. new symbol exports),
> you cannot distinguish them via exit code alone — use `--format json` and parse
> the `verdict` field.

### CI gate examples

```bash
# Fail on any break (production gate)
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && echo "ERROR — check inputs" && exit 1
[ $ret -eq 4 ] && echo "BREAKING — release blocked" && exit 1
[ $ret -eq 2 ] && echo "API_BREAK — source-level break" && exit 1
echo "OK (NO_CHANGE or COMPATIBLE)"

# Fail only on binary ABI breaks (allow API_BREAK and COMPATIBLE)
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && exit 1   # tool error
[ $ret -eq 4 ] && exit 1   # binary break only
exit 0

# Parse exact verdict via JSON
abicheck compare old.json new.json --format json -o result.json
verdict=$(python3 -c "import json; print(json.load(open('result.json'))['verdict'])")
[ "$verdict" = "BREAKING" ] && exit 1
```

---

## `abicheck compat`

ABICC-compatible mode (matches `abi-compliance-checker` exit codes):

| Exit code | Meaning |
|-----------|---------|
| `0` | No breaking changes (`COMPATIBLE` or `NO_CHANGE`) |
| `1` | `BREAKING` — binary ABI break detected |
| `2` | `API_BREAK` — source-level break (binary compatible) |
| `1` | Error — also exits `1` for tool failures (same as BREAKING) |

> **⚠️ Note:** In `compat` mode, exit `2` means `API_BREAK` (not an error — unlike
> `compare` mode where `1` is the error code). Validate your XML descriptor files
> exist before treating exit `2` as a definitive signal.

---

## Quick comparison

| Verdict / State | `compare` exit | `compat` exit |
|-----------------|---------------|---------------|
| `NO_CHANGE` | `0` | `0` |
| `COMPATIBLE` | `0` | `0` |
| `API_BREAK` | `2` | `2` |
| `BREAKING` | `4` | `1` |
| Tool error | `1` | `1` |

---

## `--strict` / `-s` flag (compat mode)

In `compat -s` mode:
- `--strict-mode full` (default): `COMPATIBLE` and `API_BREAK` → exit `1` (BREAKING)
- `--strict-mode api`: only `API_BREAK` → exit `1`; `COMPATIBLE` unchanged
