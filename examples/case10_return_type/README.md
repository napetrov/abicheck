# Case 10: Return Type Change

**Category:** Symbol API | **Verdict:** 🟡 ABI CHANGE (exit 4)

> **Note on abidiff 2.4.0:** Returns exit **4**. Semantically breaking — on
> x86-64, `int` is returned in the lower 32 bits of `rax`; `long` uses all 64 bits.
> Old callers zero-extend only 32 bits, potentially reading garbage for large values.

## What breaks
Callers compiled against v1 truncate the return value to 32 bits. For counts above
`INT_MAX`, the result is wrong or negative. This is a silent data corruption bug.

## Why abidiff catches it
Reports `return type changed: type name changed from 'int' to 'long int'`.

## Code diff

| v1.c | v2.c |
|------|------|
| `int get_count(void) { return 42; }` | `long get_count(void) { return 42; }` |

## Reproduce manually
```bash
gcc -shared -fPIC -g v1.c -o libfoo_v1.so
gcc -shared -fPIC -g v2.c -o libfoo_v2.so
abidw --out-file v1.xml libfoo_v1.so
abidw --out-file v2.xml libfoo_v2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 4
```

## How to fix
Add a new function with the new return type (e.g., `get_count_ex()` returning `long`)
and deprecate the old one. Change the SONAME on the major version bump when the old
symbol is eventually removed.

## Real-world example
`ftell()` → `ftello()` (returns `off_t` instead of `long`) is the classic example of
this class of change in the C standard library — a new function was introduced instead
of changing the old one.

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** app compiled with v1 (`get_count()` returns `int`) calls v2 which returns `long 3000000000` — truncated on read.

```bash
# Build v1 + app
gcc -shared -fPIC -g v1.c -o libfoo.so
gcc -g app.c -I. -L. -lfoo -Wl,-rpath,. -o app
./app
# → Expected: 3000000000
# → Got:      42

# Swap in v2 (returns 3000000000L)
gcc -shared -fPIC -g v2.c -o libfoo.so
./app
# → Expected: 3000000000
# → Got:      -1294967296   ← truncated to 32 bits (3000000000 mod 2^32)
```

**Why CRITICAL:** On x86-64, `int` is returned in the lower 32 bits of `rax`; `long`
uses all 64. The app zero-extends only 32 bits, reading a completely wrong value. Silent
data corruption for any count above `INT_MAX`.
