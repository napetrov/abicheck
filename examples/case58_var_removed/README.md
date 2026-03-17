# Case 58: Global Variable Removed

**Category:** Symbol API | **Verdict:** BREAKING

## What this case is about

v1 exports two global variables: `lib_version` and `lib_debug_level`.
v2 removes `lib_debug_level` from the export table (made it `static`).

Consumers that reference `lib_debug_level` directly will fail to link or
crash at runtime with a missing symbol error.

## What breaks at binary level

- **Symbol lookup fails**: `lib_debug_level` is no longer in `.dynsym`.
  The dynamic linker cannot resolve the reference → `undefined symbol` error
  or relocation failure at program startup.
- **Direct access patterns break**: Code that reads/writes the variable
  (e.g., `lib_debug_level = 3`) will fail due to unresolved symbol/relocation
  at startup, before the program begins execution.

## What abicheck detects

- **`VAR_REMOVED`**: The global variable symbol is absent from v2's export table.

**Overall verdict: BREAKING**

## How to reproduce

```bash
gcc -shared -fPIC -g bad.c  -o libbad.so
gcc -shared -fPIC -g good.c -o libgood.so

nm -D libbad.so  | grep lib_debug_level  # → D lib_debug_level
nm -D libgood.so | grep lib_debug_level  # → (nothing)

python3 -m abicheck.cli dump libbad.so  -o /tmp/v1.json
python3 -m abicheck.cli dump libgood.so -o /tmp/v2.json
python3 -m abicheck.cli compare /tmp/v1.json /tmp/v2.json
# → BREAKING: VAR_REMOVED
```

## How to fix

Keep the variable exported for backward compatibility, even if deprecated:

```c
int lib_debug_level __attribute__((deprecated)) = 0;
```

Or use a version script to control when symbols are removed.

## References

- [ELF Symbol Versioning](https://www.akkadia.org/drepper/symbol-versioning)
