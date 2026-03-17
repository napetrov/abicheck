# Verdicts

Every `abicheck compare` run produces one of five verdicts.

---

## The five verdicts

### `NO_CHANGE`
The two snapshots are **identical** — no differences found.

**CI action:** pass.

---

### `COMPATIBLE`
Changes found, but **backwards-compatible** — existing compiled consumers can upgrade without recompiling.

Examples:
- New exported symbol added
- `noexcept` specifier added/removed (mangled name unchanged; binary-compatible)
- `GLOBAL` → `WEAK` symbol binding (ELF/Linux only — weak symbols have different semantics on Mach-O/macOS; abicheck targets Linux ELF)
- Enum member added at end of enum

**CI action:** warn; do not fail. Use `-s` to promote to BREAKING if your policy requires.

---

### `COMPATIBLE_WITH_RISK`
A change that **does not break** existing compiled consumers (they are already linked and continue to work), but introduces a **deployment risk** that must be verified manually.

The library upgrade may fail on some target environments — for example, if the new library requires a newer glibc version that is absent on the deployment target.

Examples:
- New symbol version requirement added to `DT_VERNEED` (e.g. `GLIBC_2.17`) — existing binaries are safe, but the new `.so` won't load on systems with older glibc

**CI action:** warn; inspect the specific change kind and verify target environment requirements. Do not fail automatically unless your policy mandates it.

> Use `abicheck compare --format json` to check the exact `verdict` field — `COMPATIBLE_WITH_RISK` exits with code `0`, same as `COMPATIBLE`.

---

### `API_BREAK`
A **source-level API break** — the public header contract changed in a way that breaks downstream source code, but **does not break already-compiled binaries**. Pre-compiled consumers continue to work at runtime. Consumers that **recompile** against new headers may get compile errors or semantic changes.

Examples:
- Field rename (same binary layout, different source name)
- Enum member rename
- Parameter default value removed
- Reduced access level (`public` → `protected`)

**CI action:** fail in API-strict pipelines or pipelines that test building from source; warn in ABI-only gates.

> **Note:** `abicheck compat` *does* emit exit code `2` for `API_BREAK` conditions.
> However, the `compat` HTML/text report uses ABICC-style phrasing
> ("⚠️ API_BREAK — Source-level API change — recompilation required") rather than a bare
> `API_BREAK` verdict string. Use `abicheck compare --format json` for machine-readable
> verdict values.

---

### `BREAKING`
A **binary ABI break** — existing compiled consumers malfunction when the library is updated.

Examples:
- Symbol removed from `.so`
- Function parameter type changed
- Struct field removed or offset shifted
- C++ vtable reordered (virtual method inserted)
- `const` qualifier added to global variable (moves to `.rodata`, breaks writes)

**CI action:** always fail; do not ship.

---

## CI policy templates (compare mode)

### Strict production gate
```bash
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && echo "ERROR — check tool inputs" && exit 1
[ $ret -eq 4 ] && echo "BREAKING — release blocked" && exit 1
[ $ret -eq 2 ] && echo "API_BREAK — source-level break" && exit 1
echo "OK (NO_CHANGE or COMPATIBLE)"
```

### Warning-only gate
```bash
abicheck compare old.json new.json --format json -o result.json
ret=$?
[ $ret -eq 1 ] && echo "::error::tool error" && exit 1
[ $ret -eq 4 ] && echo "::error::BREAKING ABI change" && exit 1
[ $ret -eq 2 ] && echo "::warning::API_BREAK (source-level)"
verdict=$(python3 -c "import json; print(json.load(open('result.json'))['verdict'])" 2>/dev/null || echo "")
[ "$verdict" = "COMPATIBLE" ] && echo "::warning::COMPATIBLE ABI change (new symbols or compatible modifications)"
echo "ABI check passed"
```

### Permissive gate (binary breaks only)
```bash
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && exit 1   # tool error
[ $ret -eq 4 ] && exit 1   # BREAKING only; API_BREAK (exit 2) allowed
exit 0
```

> For `compat` mode CI patterns, see [ABICC Compatibility](../user-guide/from-abicc.md).
> Note: in compat mode, exit `1` = BREAKING, exit `2` = API_BREAK.
> Non-verdict failures use extended codes (`3`–`11`) — see [Exit Codes](../reference/exit-codes.md).

---

Full exit code reference: [Exit Codes](../reference/exit-codes.md)
