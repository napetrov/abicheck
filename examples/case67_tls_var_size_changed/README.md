# Case 67: TLS Variable Size Changed

**Category:** Variable ABI | **Verdict:** BREAKING

## What breaks

The thread-local `ErrorCtx` struct grows from 68 bytes (v1) to 264 bytes (v2)
by expanding the `message` buffer from 64 to 256 bytes and adding a
`source_line` field. This changes the layout of the TLS (Thread-Local Storage)
segment.

The adjacent TLS variable `tls_log_level` shifts to a different offset within
the TLS block. A consumer compiled against v1 accesses `tls_log_level` at the
old offset, which now falls inside the expanded `tls_error.message[]` buffer —
reading and writing the wrong memory.

## Why this matters

Thread-local variables (`__thread` / `thread_local`) are allocated in a
per-thread TLS block. The dynamic linker computes each variable's offset within
this block based on the **symbol size** recorded in the `.dynsym` table. When a
TLS variable's size changes:

- Other TLS variables in the same module may shift to different offsets
- Consumers that hardcoded the old offset (via copy relocation or direct TLS
  access model) read/write the wrong location
- The corruption is **per-thread** and **non-deterministic** — different threads
  may exhibit different symptoms depending on allocation order

This is especially dangerous in logging/error-handling libraries where:
- TLS variables are accessed on every function call (hot path)
- The corruption may not manifest until a specific thread hits a specific code path
- Race conditions between threads make the bug extremely hard to reproduce

## Code diff

```c
// v1: ErrorCtx is 68 bytes (4 + 64)
typedef struct ErrorCtx {
    int   code;
    char  message[64];
} ErrorCtx;

// v2: ErrorCtx is 264 bytes (4 + 256 + 4)
typedef struct ErrorCtx {
    int   code;
    char  message[256];   // was 64
    int   source_line;    // new
} ErrorCtx;
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build old library + app
gcc -shared -fPIC -g v1.c -o liblogger.so
gcc -g app.c -L. -llogger -Wl,-rpath,. -o app
./app
# → log_level = 42 (expected 42)
# → error code = 404 (expected 404)
# → error msg  = "resource not found"
# → log_level  = 42 (expected 42)

# Swap in new library (no recompile)
gcc -shared -fPIC -g v2.c -o liblogger.so
./app
# → log_level = 42 (expected 42)
# → error code = 404 (expected 404)
# → error msg  = "resource not found"
# → log_level  = 0 (expected 42)
# → CORRUPTION: TLS variable layout shifted
```

**Why CRITICAL:** The expanded `tls_error` struct overlaps with where the app
expects `tls_log_level` to be. Writing to `tls_error.message` can overwrite
`tls_log_level`, and vice versa. The corruption is silent — no crash, just
wrong values that lead to incorrect program behavior.

## How to fix

1. **Use accessor functions**: don't export TLS variables directly; provide
   `logger_get_log_level()` / `logger_set_log_level()` instead
2. **Use opaque pointers**: return a `void*` to the TLS block and let the
   library manage offsets internally
3. **Freeze exported TLS variable sizes**: if you must export TLS variables,
   treat their `sizeof` as part of the ABI contract
4. **Add reserved space**: include padding in the struct for future expansion

## Real-world example

glibc's `errno` is a TLS variable (`__thread int errno`). Its size (4 bytes)
has been frozen since glibc 2.0 — changing it would break every C program in
existence. Similarly, `__thread locale_t __locale` in glibc has a fixed size
that cannot change without breaking the ABI.

The Go runtime's goroutine-local storage (`g` struct) has caused compatibility
issues when its size changed between Go versions, breaking CGo interop with
pre-built shared libraries.

## abicheck detection

abicheck detects this as `tls_var_size_changed` (BREAKING) by comparing the
`st_size` field in the `.dynsym` entry for TLS symbols (those with `STT_TLS`
type) between the two library versions.

## References

- [ELF Handling For Thread-Local Storage](https://www.akkadia.org/drepper/tls.pdf)
- [System V ABI — Thread-Local Storage](https://refspecs.linuxfoundation.org/elf/x86_64-abi-0.99.pdf)
- [DWARF5 §2.12 — Thread-Local Storage](https://dwarfstd.org/doc/DWARF5.pdf)
