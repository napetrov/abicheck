# Exit Codes

`abicheck` uses different exit codes depending on the command (`compare` vs `compat`).

---

## `abicheck compare`

| Exit code | Meaning |
|-----------|---------|
| `0` | `NO_CHANGE` **or** `COMPATIBLE` — no binary ABI break detected |
| `2` | `API_BREAK` — source-level break (compile-time only; existing binaries are safe) |
| `4` | `BREAKING` — binary ABI break; existing consumers will malfunction |

> **⚠️ Important:** Exit code `0` means **either** `NO_CHANGE` or `COMPATIBLE`.
> If you use `$? -eq 0` to detect "nothing changed", you will silently miss `COMPATIBLE`
> changes (e.g. new exported symbols). Use `--format json` and parse the `verdict` field
> for precise detection, or use `--fail-on breaking` / `--fail-on api_break`.

### CI gate recommendations

```bash
# Strict: fail on any ABI/API change (CI production gate)
abicheck compare old.json new.json
[ $? -eq 0 ] || exit 1

# Permissive: fail only on binary ABI breaks (allow additive changes)
abicheck compare old.json new.json
ret=$?
[ $ret -eq 4 ] && exit 1  # only fail on BREAKING

# Parse precise verdict
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

> **⚠️ Migration note:** If you are migrating from `abi-compliance-checker`, the
> `compat` exit codes are intentionally compatible. However, if you switch to
> `abicheck compare` (recommended for new integrations), the exit codes are different.
> See [Migrating from ABICC](../migration/from_abicc.md) for a full mapping table.

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

