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
- `noexcept` specifier added/removed (Itanium ABI mangling unchanged)
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

**CI action:** fail in API-strict pipelines; warn in ABI-only gates.

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

`FUNC_NOEXCEPT_REMOVED` ChangeKind maps to `COMPATIBLE` (Itanium ABI mangling unchanged).
But **case15** verdict is `BREAKING` — because removing `noexcept` with `throw()` on `libstdc++`
triggers `SYMBOL_VERSION_REQUIRED_ADDED: GLIBCXX_3.4.21` (ELF hard break).
The ChangeKind and the case verdict differ because verdict = worst of all detected ChangeKinds.

---

## CI policy templates

### Strict production gate
```bash
abicheck compare old.json new.json
ret=$?
[ $ret -eq 4 ] && echo "BREAKING — release blocked" && exit 1
[ $ret -eq 2 ] && echo "API_BREAK — source-level break" && exit 1
```

### Warning-only gate
```bash
abicheck compare old.json new.json
ret=$?
[ $ret -eq 4 ] && echo "::error::BREAKING ABI change" && exit 1
[ $ret -eq 2 ] && echo "::warning::API_BREAK (source-level)"
```

### Permissive gate (migration from ABICC)
```bash
# Only fail on binary breaks; allow API_BREAK during migration period
abicheck compare old.json new.json
[ $? -eq 4 ] && exit 1 || exit 0
```

---

## Exit code summary

| Verdict | `compare` exit | `compat` exit |
|---------|---------------|---------------|
| `NO_CHANGE` | `0` | `0` |
| `COMPATIBLE` | `0` | `0` |
| `API_BREAK` | `2` | `2` |
| `BREAKING` | `4` | `1` |

> ⚠️ `compare` exits `0` for both `NO_CHANGE` and `COMPATIBLE`. See [exit_codes.md](../exit_codes.md).

Full ChangeKind reference: [reference/change_kinds.md](../reference/change_kinds.md)
