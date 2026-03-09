# Case 15 — `noexcept` Changed

**abicheck verdict: COMPATIBLE (informational/warning)**

## What changes

| Version | Signature |
|---------|-----------|
| v1 | `void reset() noexcept;` |
| v2 | `void reset();` |

## Why this is NOT a binary ABI break

In the Itanium C++ ABI (GCC/Clang on Linux/macOS), `noexcept` does **not** change
the mangled name for function symbols. The **symbol name is identical** in the `.so`,
so existing binaries resolve the same symbol and calls proceed normally.

abicheck classifies this as **COMPATIBLE** because:
- No symbol resolution failure occurs at load time or call time.
- No type layout, vtable, or calling convention change is involved.
- The change is a **source-level contract concern**, not a binary linkage break.

## What it does affect (source-level concerns)

- **C++17 function-pointer types**: `noexcept` is part of the function type in C++17
  (P0012R1), so `void(*)() noexcept` and `void(*)()` are distinct types. This can
  cause template instantiation mismatches in source code — but not in already-compiled
  binaries.
- **Exception-handling behavior**: code compiled against v1 may omit landing pads,
  assuming no unwinding is needed. If v2's `reset()` throws, `std::terminate` is
  called. This is a behavioral contract concern, not a linkage failure.

The **symbol name itself is identical** in the `.so` (no mangling difference for
member functions in GCC), so `abidiff` sees no change.

## Why abidiff misses it

`abidiff` compares DWARF type information and symbol tables. `noexcept` is **not
stored in DWARF** — it is purely a source-level annotation. abidiff has no way to
detect the change.

## Why ABICC catches it

ABICC (ABI Compliance Checker) parses **C++ headers** using GCC's compiler internals
and its own header analysis infrastructure. It sees the `noexcept` specifier on the
function declaration and records it as part of the function's ABI profile. When v1 and
v2 headers differ in `noexcept`, ABICC flags it.

## Real-world example

In **Folly** (Facebook's C++ library), several internal `reset()` and `destroy()`
methods had `noexcept` removed during a refactor. Downstream projects compiled with
old headers started hitting silent `std::terminate` crashes when running with the
new `.so`. The breakage was caught by ABICC in CI before the release.

## Code diff

```diff
-void reset() noexcept;
+void reset();
```

## Reproduce steps

```bash
cd examples/case15_noexcept_change

# Build v1 and v2
g++ -shared -fPIC -std=c++17 -g v1.cpp -o libv1.so
g++ -shared -fPIC -std=c++17 -g v2.cpp -o libv2.so

# abidiff: expects no output (misses the change)
abidw --out-file v1.xml libv1.so
abidw --out-file v2.xml libv2.so
abidiff v1.xml v2.xml || true   # exits 0 — misses it!

# ABICC: catches it via header diff
abi-compliance-checker -lib Buffer -v1 1.0 -v2 2.0 \
  -header v1.cpp -header v2.cpp \
  -gcc-options "-std=c++17"
```

## Real Failure Demo

**Severity: CRITICAL (behavioral, not linkage)**

**Scenario:** app compiled against v1 (`reset()` noexcept) calls v2 which throws — exception propagates through a noexcept frame → `std::terminate`.

> **Important:** This demo conflates two changes: (1) removing `noexcept` from the
> declaration, and (2) adding `throw` to the implementation. Removing `noexcept` alone
> does **not** cause a crash — the binary links and runs identically. The crash only
> occurs because v2 also introduces throwing code. The ABI verdict remains **COMPATIBLE**
> (same symbol resolves), but removing `noexcept` increases the *risk* of this behavioral
> failure if the implementation later throws.

```bash
# Build v1 + app (app includes v1.h which declares reset() noexcept)
g++ -shared -fPIC -std=c++17 -g v1.cpp -o libbuf.so
g++ -std=c++17 -g app.cpp -I. -L. -lbuf -Wl,-rpath,. -o app
./app
# → Calling reset()...
# → reset() completed OK

# Swap in v2 (reset() throws)
g++ -shared -fPIC -std=c++17 -g v2.cpp -o libbuf.so
./app
# → terminate called after throwing an instance of 'std::runtime_error'
#      what():  reset failed
# → Aborted (core dumped)
```

**Why CRITICAL (behavioral):** The caller was compiled with the assumption that `reset()`
is `noexcept`, so no try/catch or landing pad was generated. When v2 throws, the exception
propagates through the noexcept frame and `std::terminate` is called unconditionally — no
recovery possible. Note: the binary linkage is fine (COMPATIBLE); the crash is a behavioral
contract violation, not a symbol resolution failure.

## Note on test expectations

The integration tests expect **BREAKING** for this case. This is because `v2.cpp`
includes `<stdexcept>`, which introduces a new `GLIBC_*` version requirement
(`SYMBOL_VERSION_REQUIRED_ADDED`). The break detected by the tool is from the
new glibc dependency, **not** from the `noexcept` removal itself. The ABI verdict
for the `noexcept` change in isolation remains **COMPATIBLE** — the mangled symbol
is identical.
