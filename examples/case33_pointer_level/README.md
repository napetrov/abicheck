# Case 33 -- Pointer Level Change


**Verdict:** 🔴 BREAKING
**abicheck verdict: BREAKING**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `void process(int *data); int *get_buffer(void);` |
| v2 | `void process(int **data); int **get_buffer(void);` |

## Why this is a binary ABI break

The caller passes a raw `int*` but the v2 library dereferences it as `int**`,
treating the pointed-to integer value as a pointer address. This causes an
immediate segfault or silent memory corruption. Similarly, `get_buffer()` now
returns an `int**` which the caller treats as `int*`, dereferencing a pointer-to-pointer
as if it were a flat buffer.

## Code diff

```diff
-void process(int *data);
-int *get_buffer(void);
+void process(int **data);     /* pointer level increased */
+int **get_buffer(void);       /* pointer level increased */
```

## Real Failure Demo

**Severity: CRITICAL**

```bash
# Build v1 lib + app
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -g app.c -I. -L. -lv1 -Wl,-rpath,. -o app
./app
# -> process(&val) succeeded, val = 42
# -> get_buffer()[0] = 99

# Swap to v2
gcc -shared -fPIC -g v2.c -o libv1.so
./app
# -> SEGFAULT: v2's process() does **data, treating the int* as int**
#    and get_buffer() returns int** cast to int* -> crash on dereference
```

**Why CRITICAL:** The library interprets a flat pointer as a double pointer.
`**data` dereferences the integer value 42 as a memory address, which is
almost certainly an unmapped page, causing an immediate segmentation fault.

## Why runtime result may differ from verdict
Pointer level change: wrong dereference depth — SIGSEGV
