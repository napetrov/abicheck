# Case 12: Function Disappears (Moved to Inline)

**Category:** Symbol API | **Verdict:** 🔴 BREAKING (exit 12)

## What breaks
Any binary dynamically linked against v1 will fail to load with
`undefined symbol: fast_add` when upgraded to v2. Even if the function is still
available as an inline in a header, the `.so` no longer exports the symbol,
so pre-built binaries have nowhere to resolve it.

## Why abidiff catches it
Reports `1 Removed function: fast_add` with exit **12** (breaking removal).

## Code diff

| v1.c | v2.c |
|------|------|
| `int fast_add(int a, int b) { return a+b; }` | *(function removed from .so)* |
| | `int other_func(int x) { return x; }` |

## Reproduce manually
```bash
gcc -shared -fPIC -g v1.c -o libfoo_v1.so
gcc -shared -fPIC -g v2.c -o libfoo_v2.so
abidw --out-file v1.xml libfoo_v1.so
abidw --out-file v2.xml libfoo_v2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 12
```

## How to fix
Keep the exported wrapper in the `.so` even if the implementation moves to an inline.
The wrapper can simply call the inline: `int fast_add(int a, int b) { return _fast_add_impl(a,b); }`.
Only remove it on a SONAME-bumping major release.

## Real-world example
Several C++ standard library implementors have moved functions to inlines for
performance and then had to keep exported stubs for ABI compatibility — libstdc++'s
`std::string` refactor in GCC 5 is the canonical cautionary tale.
