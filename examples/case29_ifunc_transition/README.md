# Case 29 — GNU IFUNC Transition

**abicheck verdict: COMPATIBLE (informational/warning)**

## What changes

| Version | ELF symbol type |
|---------|----------------|
| v1 | `dispatch: STT_FUNC` (regular function) |
| v2 | `dispatch: STT_GNU_IFUNC` (indirect function) |

## What is GNU IFUNC?

GNU IFUNC (indirect function) is a mechanism for runtime CPU dispatch. Instead of
pointing directly to the function body, the symbol points to a **resolver function**
that returns the address of the best implementation for the current CPU. The dynamic
linker calls the resolver at load time and patches the GOT entry.

Common uses:
- glibc's `memcpy`, `strlen`, etc. use IFUNC to select SSE/AVX/NEON implementations.
- Math libraries dispatch to architecture-specific code paths.

## Why this is NOT a binary ABI break

The transition from regular function to IFUNC (or back) is **transparent to callers**.
The PLT/GOT mechanism handles the indirection automatically:

1. Caller calls `dispatch()` through the PLT (same as before).
2. Dynamic linker resolves the symbol — if IFUNC, calls the resolver first.
3. GOT entry is patched with the final function address.
4. All subsequent calls go directly to the resolved address.

abicheck classifies this as **COMPATIBLE** because:
- The calling convention is unchanged.
- The function signature is unchanged.
- Symbol resolution succeeds transparently.
- This is purely an implementation optimization.

## What it does affect

- **Debugger behavior**: breakpoints on IFUNC symbols may behave differently
  (breakpoint hits the resolver on first call, then the resolved implementation).
- **Static analysis tools**: may not recognize the indirection.
- **Older dynamic linkers**: very old ld.so versions may not support IFUNC
  (but this is a deployment concern, not an ABI contract issue).

## Code diff

```diff
-int dispatch(int x) { return x * 2; }
+static int dispatch_generic(int x) { return x * 2; }
+static int dispatch_avx(int x) { /* AVX implementation */ return x * 2; }
+
+/* IFUNC resolver — called by dynamic linker at load time */
+int dispatch(int x) __attribute__((ifunc("resolve_dispatch")));
+static void *resolve_dispatch(void) {
+    return has_avx() ? (void*)dispatch_avx : (void*)dispatch_generic;
+}
```
