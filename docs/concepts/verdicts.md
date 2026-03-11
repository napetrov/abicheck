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
- `noexcept` specifier added/removed _(Itanium ABI mangling unchanged for non-template, non-function-pointer contexts; in C++17+, `noexcept` is part of function type and may affect mangling in template/function-pointer contexts — see [case15 edge case](#edge-case-noexcept-case15))_
- `GLOBAL` → `WEAK` symbol binding
- Enum member added at end of enum

**CI action:** warn; do not fail. Use `--strict` to block if your policy requires.

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

> **Note:** `abicheck compat` mode does not emit `API_BREAK` — it follows ABICC's
> binary vocabulary (`COMPATIBLE` / `BREAKING` / `NO_CHANGE`).

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
for non-template, non-function-pointer contexts.

However, **case15** is classified `BREAKING` because the function previously had `throw()` —
the legacy C++03/C++11 exception specification — which caused the symbol to carry a versioned
requirement (`SYMBOL_VERSION_REQUIRED_ADDED: GLIBCXX_3.4.21`). Removing `throw()` drops
that versioned symbol from the binary, breaking consumers that were linked against it.

The verdict is the **worst** of all detected ChangeKinds — `FUNC_NOEXCEPT_REMOVED` alone is
`COMPATIBLE`, but combined with the ELF `SYMBOL_VERSION_REQUIRED_ADDED` event it becomes `BREAKING`.

---

## CI policy templates

### Strict production gate
```bash
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && echo "ERROR — tool failed (check inputs)" && exit 1
[ $ret -eq 4 ] && echo "BREAKING — release blocked" && exit 1
[ $ret -eq 2 ] && echo "API_BREAK — source-level break" && exit 1
echo "OK (NO_CHANGE or COMPATIBLE)"
```

### Warning-only gate
```bash
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && echo "::error::tool error" && exit 1
[ $ret -eq 4 ] && echo "::error::BREAKING ABI change" && exit 1
[ $ret -eq 2 ] && echo "::warning::API_BREAK (source-level)"
echo "ABI check passed"
```

### Permissive gate (migration from ABICC)
```bash
# Only fail on binary breaks; allow API_BREAK during migration period
abicheck compare old.json new.json
ret=$?
[ $ret -eq 1 ] && exit 1   # tool error
[ $ret -eq 4 ] && exit 1   # BREAKING only
exit 0
```

---

## Exit code summary

| Verdict | `compare` exit | `compat` exit |
|---------|---------------|---------------|
| `NO_CHANGE` | `0` | `0` |
| `COMPATIBLE` | `0` | `0` |
| `API_BREAK` | `2` | `2` |
| `BREAKING` | `4` | `1` |
| Error | `1` | `2` |

> ⚠️ `compare` exits `0` for both `NO_CHANGE` and `COMPATIBLE`. If your pipeline
> should warn on `COMPATIBLE` changes (e.g. new symbol exports), you cannot
> distinguish them via exit code alone — use `--format json` and check the `verdict` field.

Full ChangeKind reference: [reference/change_kinds.md](../reference/change_kinds.md)
