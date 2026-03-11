# Verdicts

Every `abicheck compare` run produces one of four verdicts.

---

## The four verdicts

### `NO_CHANGE`
The two snapshots are **identical** — no differences found.

**CI action:** pass.

---

### `COMPATIBLE`
Changes found, but **backwards-compatible** — existing compiled consumers can upgrade without recompiling.

Examples:
- New exported symbol added
- `noexcept` specifier added/removed *(for plain non-template functions; in C++17+, `noexcept` is part of function type and can affect mangling in function-pointer/template contexts — see [edge case](#edge-case-noexcept-case15). Note: abicheck does not currently flag function-pointer or template context noexcept changes separately.)*
- `GLOBAL` → `WEAK` symbol binding (ELF/Linux only — weak symbols have different semantics on Mach-O/macOS; abicheck targets Linux ELF)
- Enum member added at end of enum

**CI action:** warn; do not fail. Use `-s` to promote to BREAKING if your policy requires.

---

### `API_BREAK`
A **source-level (compile-time) break** that does not break existing compiled binaries.
Pre-compiled consumers still work at runtime. Consumers that **recompile** against new headers get compile errors.

Examples:
- Field rename (same binary layout, different source name)
- Enum member rename
- Parameter default value removed
- Reduced access level (`public` → `protected`)

**CI action:** fail in API-strict pipelines or pipelines that test building from source; warn in ABI-only gates.

> **Note:** `abicheck compat` *does* emit exit code `2` for `API_BREAK` conditions.
> However, the `compat` HTML/text report uses ABICC-style phrasing
> ("⚠️ API_BREAK — Source-level API change, binary compatible") rather than a bare
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

## Edge case: `noexcept` (case15)

`FUNC_NOEXCEPT_REMOVED` (removing a `noexcept` specifier) normally maps to `COMPATIBLE`
for plain non-template functions.

However, **case15** is classified `BREAKING`. The function was compiled with `throw()` —
the legacy C++03 exception specification. Compiled with `-std=c++03`, `throw()` generates
a call to `__cxa_call_unexpected`, which pulls in the `GLIBCXX_3.4.21` version symbol.
Removing `throw()` drops that versioned symbol from the binary, triggering
`SYMBOL_VERSION_REQUIRED_ADDED: GLIBCXX_3.4.21` — a hard binary break for consumers
linked against the old symbol version.

The verdict is the **worst** of all detected ChangeKinds: `FUNC_NOEXCEPT_REMOVED` alone
is `COMPATIBLE`, but combined with `SYMBOL_VERSION_REQUIRED_ADDED` it becomes `BREAKING`.

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

> For `compat` mode CI patterns, see [Migrating from ABICC](../migration/from_abicc.md).
> Note: in compat mode, exit `1` = BREAKING, exit `2` = API_BREAK **or** tool error.
> Use `--format json` to distinguish tool errors from real `API_BREAK` verdicts.

---

## Exit code summary

| Verdict | `compare` exit | `compat` exit |
|---------|---------------|---------------|
| `NO_CHANGE` | `0` | `0` |
| `COMPATIBLE` | `0` | `0` |
| `API_BREAK` | `2` | `2` |
| `BREAKING` | `4` | `1` |
| Tool error | `1` | `2` |

> ⚠️ `compare` exits `0` for both `NO_CHANGE` and `COMPATIBLE`.
> Use `--format json` + `verdict` field to distinguish them in automation.

Full reference: [exit_codes.md](../exit_codes.md)
