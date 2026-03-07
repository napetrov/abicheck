# Case 15 — `noexcept` Removed

## What changes

| Version | Signature |
|---------|-----------|
| v1 | `void reset() noexcept;` |
| v2 | `void reset();` |

## What breaks at binary level

In the Itanium C++ ABI (GCC/Clang on Linux/macOS) `noexcept` **does** affect the
mangled name for some function-pointer typedefs (C++17+), and more importantly it
changes the **exception-handling personality** of call sites:

- Code compiled against v1 wraps calls to `reset()` with an assumption that no
  unwinding is needed. The compiler may omit landing pads in callers.
- With v2, `reset()` *can* throw. A caller compiled with v1 headers will not have
  the landing pad → exception propagates through a `noexcept` frame → `std::terminate`.

The **symbol name itself is identical** in the `.so` (no mangling difference for
member functions in GCC), so `abidiff` sees no change.

## Why abidiff misses it

`abidiff` compares DWARF type information and symbol tables. `noexcept` is **not
stored in DWARF** — it is purely a source-level annotation. abidiff has no way to
detect the change.

## Why ABICC catches it

ABICC (ABI Compliance Checker) parses the **C++ header AST** via libclang. It sees
the `noexcept` specifier on the function declaration and records it as part of the
function's ABI profile. When v1 and v2 headers differ in `noexcept`, ABICC flags it.

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
