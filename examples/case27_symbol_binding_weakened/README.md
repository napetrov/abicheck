# Case 27 — Symbol Binding Weakened (GLOBAL → WEAK)

**abicheck verdict: COMPATIBLE (informational/warning)**

## What changes

| Version | ELF binding |
|---------|------------|
| v1 | `foo: GLOBAL DEFAULT` |
| v2 | `foo: WEAK DEFAULT` |

This typically happens when a library applies `__attribute__((weak))` to a previously
strong (GLOBAL) symbol, or when a linker script changes binding.

## Why this is NOT a binary ABI break

A WEAK symbol is still **exported and resolvable** by the dynamic linker. Existing
binaries that linked against the GLOBAL version of `foo` will find and use the
(now WEAK) symbol without any change in behavior.

abicheck classifies this as **COMPATIBLE** because:
- The symbol is still present in `.dynsym` and resolvable.
- No calling convention, type layout, or signature change occurs.
- The dynamic linker resolves WEAK symbols the same way as GLOBAL when no
  override is present.

## What it does affect

- **Symbol interposition**: a WEAK symbol can be overridden by a GLOBAL definition
  from another shared object or the main executable. If the consumer's environment
  provides an alternative definition, the WEAK version may not be used.
- **Linker behavior**: some linkers treat WEAK symbols differently during static
  linking (e.g., not pulling the object file from an archive).

These are deployment/interposition concerns, not binary compatibility failures.

## Contrast with BREAKING binding changes

The reverse direction — WEAK → GLOBAL (`SYMBOL_BINDING_STRENGTHENED`) — is also
classified as COMPATIBLE. Neither direction breaks existing symbol resolution.

## Code diff

```diff
 /* v1: normal definition */
-int foo(void) { return 42; }
+__attribute__((weak)) int foo(void) { return 42; }
```
