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
> you cannot distinguish them via exit code alone — use `--format json` and check the
> `verdict` field.

### CI gate recommendations

```bash
# Strict: fail on any break (production gate)
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && echo "ERROR — check tool inputs" && exit 1
[ $ret -eq 4 ] && echo "BREAKING — release blocked" && exit 1
[ $ret -eq 2 ] && echo "API_BREAK — source-level break" && exit 1
echo "OK"

# Permissive: fail only on binary ABI breaks
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && exit 1   # tool error
[ $ret -eq 4 ] && exit 1   # binary break only
exit 0

# Parse exact verdict
abicheck compare old.json new.json --format json -o result.json
verdict=$(python3 -c "import json; print(json.load(open('result.json'))['verdict'])")
[ "$verdict" = "BREAKING" ] && exit 1
```

---

## `abicheck compat`

ABICC-compatible mode uses a **different exit code scheme** (matches `abi-compliance-checker`):

| Exit code | Meaning |
|-----------|---------|
| `0` | No breaking changes (COMPATIBLE or NO_CHANGE) |
| `1` | `BREAKING` — binary ABI break detected |
| `2` | `API_BREAK` (source-level break) **or** error (descriptor parse failure, missing files) |

> **⚠️ Migration note:** Exit code `2` conflates `API_BREAK` with tool errors in `compat` mode.
> Validate that your input XML files exist before relying on exit `2` as an API_BREAK signal.
> See [Migrating from ABICC](../migration/from_abicc.md) for the full mapping.

---

## Quick comparison

| Verdict | `compare` exit | `compat` exit |
|---------|---------------|---------------|
| `NO_CHANGE` | `0` | `0` |
| `COMPATIBLE` | `0` | `0` |
| `API_BREAK` | `2` | `2` |
| `BREAKING` | `4` | `1` |
| Error | `1` | `2` |

---

## `--strict` / `-s` flag (compat mode)

In `compat -s` mode, `COMPATIBLE` and `API_BREAK` are promoted to `BREAKING`,
so exit code `1` is also returned for those cases.
