# Case 39: Variable Const Change

**Category:** Global Variable Qualifiers | **Verdict:** NO_CHANGE (headers-only detection limitation)

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `extern int g_buffer_size` (mutable); `extern const int g_max_retries` (const); `extern int g_legacy_flag` (exists) |
| v2 | `extern const int g_buffer_size` (became const); `extern int g_max_retries` (lost const); `g_legacy_flag` removed |

## Why this isn't detected by headers-only analysis

When abicheck performs headers-only analysis (without compiled `.so` files), const
qualifiers on global variables and variable removal are not visible in the header parse
output in a way that triggers ABI break detection. The actual binary impact is real:

1. **`g_buffer_size` became const** — moved from `.data` to `.rodata`. Old binaries that
   write to it (legal in v1) will get a SIGSEGV because the memory page is now read-only.
2. **`g_max_retries` lost const** — old binaries may have inlined the constant value `3`
   at compile time. The library now holds `5`, but the app still uses `3` (ODR violation).
3. **`g_legacy_flag` removed** — old binaries referencing it get an undefined symbol error
   at load time.

With full `.so`-level analysis (abidiff), these would all be detected. But the
headers-only checker reports NO_CHANGE.

## Code diff

```diff
-extern int g_buffer_size;
+extern const int g_buffer_size;

-extern const int g_max_retries;
+extern int g_max_retries;

-extern int g_legacy_flag;
+/* g_legacy_flag REMOVED */
```

```diff
-int g_buffer_size = 4096;
+const int g_buffer_size = 8192;

-const int g_max_retries = 3;
+int g_max_retries = 5;

-int g_legacy_flag = 1;
+/* g_legacy_flag removed */
```

## Real Failure Demo

**Severity: HIGH (but undetected by headers-only check)**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 lib + app
gcc -shared -fPIC -g v1.c -o libfoo.so
gcc -g app.c -I. -L. -lfoo -Wl,-rpath,. -o app
./app
# → g_buffer_size  = 4096
# → g_max_retries  = 3
# → g_legacy_flag  = 1
# → get_config()   = 4096
# → g_buffer_size after write = 2048

# Swap to v2 (no recompile of app)
gcc -shared -fPIC -g v2.c -o libfoo.so
./app
# → ./app: symbol lookup error: ./app: undefined symbol: g_legacy_flag
#
# If g_legacy_flag reference were removed, the write to g_buffer_size
# would cause SIGSEGV (it now lives in .rodata).
```

**Why HIGH:** Variable removal causes immediate load failure. Const promotion causes
segfaults on write. Const removal causes silent value staleness. All are real ABI breaks
that headers-only analysis misses.

## Reproduce manually
```bash
gcc -shared -fPIC -g v1.c -o libv1.so
gcc -shared -fPIC -g v2.c -o libv2.so
abidw --out-file v1.xml libv1.so
abidw --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 12 (detected at binary level)
```

## How to fix
Never change const qualification on exported global variables. If a variable needs to
become read-only, provide an accessor function instead (`int get_buffer_size(void)`).
Never remove exported variables without a SONAME bump.
