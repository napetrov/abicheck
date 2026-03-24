# Case 72: Function Ref-Qualifier Changed

**Category:** Function ABI | **Verdict:** BREAKING

## What breaks

The ref-qualifier on `Buffer::consume()` changes from `&` (lvalue) to `&&`
(rvalue). In the Itanium C++ ABI, ref-qualifiers are part of the mangled name:

- v1 symbol: `_ZNR6Buffer7consumeEv` (the `R` encodes lvalue ref-qualifier)
- v2 symbol: `_ZNO6Buffer7consumeEv` (the `O` encodes rvalue ref-qualifier)

Old binaries linked against v1 request the lvalue-qualified symbol. Since v2
only exports the rvalue-qualified version, the dynamic linker reports "undefined
symbol" at load time.

This is different from case22 (const-qualifier change) because ref-qualifiers
(`&`/`&&`) are a separate dimension of function qualification, with their own
mangling rules and different semantic implications for overload resolution.

## Why abicheck catches it

Symbol comparison detects the mangled name change caused by the ref-qualifier
flip (`func_ref_qual_changed`). This is flagged as BREAKING because the old
symbol no longer exists.

## Code diff

```cpp
// v1.h — lvalue ref-qualified (mangled with 'R')
class Buffer {
    int consume() &;
};

// v2.h — rvalue ref-qualified (mangled with 'O')
class Buffer {
    int consume() &&;
};
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 and app
g++ -shared -fPIC -g v1.cpp -o libbuffer.so
g++ -g app.cpp -L. -lbuffer -Wl,-rpath,. -o app
./app
# -> consume() = 42
# -> Expected: 42

# Verify v1 exports lvalue ref-qualified symbol
nm -D libbuffer.so | c++filt | grep consume
# -> T Buffer::consume() &

# Build v2 (rvalue ref-qualified)
g++ -shared -fPIC -g v2.cpp -o libbuffer.so

# Verify v2 exports rvalue ref-qualified symbol
nm -D libbuffer.so | c++filt | grep consume
# -> T Buffer::consume() &&

./app
# -> ./app: symbol lookup error: undefined symbol: _ZNR6Buffer7consumeEv
```

**Why CRITICAL:** The ref-qualifier is encoded in the mangled symbol name.
Changing `&` to `&&` is equivalent to renaming the symbol. The old binary
cannot find the function at all.

## How to fix

Provide both overloads to maintain backward compatibility:

```cpp
class Buffer {
    int consume() &;   /* keep for existing callers */
    int consume() &&;  /* add new rvalue overload */
};
```

## Real-world example

C++ libraries that adopt move semantics (e.g., `std::optional::value()`,
range-v3 view adapters) sometimes change existing methods from unqualified to
ref-qualified. This is a source-level improvement but an ABI-breaking change
that must be gated behind a SONAME bump.

## References

- [Itanium C++ ABI: Ref-qualifier mangling](https://itanium-cxx-abi.github.io/cxx-abi/abi.html#mangling)
- [C++ Standard: Member function ref-qualifiers (dcl.fct §4)](https://www.open-std.org/jtc1/sc22/wg21/docs/papers/2023/n4950.pdf)
