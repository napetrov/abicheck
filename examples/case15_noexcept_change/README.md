# Case 15 — `noexcept` Changed

**abicheck verdict: BREAKING**

## What changes

| Version | Signature |
|---------|-----------|
| v1 | `void reset() noexcept;` |
| v2 | `void reset();` (throws `std::runtime_error`) |

## Why this IS a binary ABI break in this case

Although removing `noexcept` from a function declaration **alone** does not change the
mangled symbol name in the Itanium C++ ABI, the **v2 implementation also introduces
a `throw std::runtime_error(...)`**. This causes a new GLIBCXX version requirement:

```
libv1.so: GLIBCXX_3.4   (no throw → no std::runtime_error dependency)
libv2.so: GLIBCXX_3.4   +   GLIBCXX_3.4.21  (std::runtime_error)
```

abicheck detects `SYMBOL_VERSION_REQUIRED_ADDED: GLIBCXX_3.4.21 (from libstdc++.so.6)` —
this is a genuine binary ABI break because:
- Old consumers linked against a system without `GLIBCXX_3.4.21` will fail at load time.
- The dynamic linker requires all `DT_VERNEED` entries to be satisfied before execution.

## The two distinct scenarios for `noexcept` removal

| Scenario | Change | Binary impact | abicheck verdict |
|---|---|---|---|
| Remove `noexcept` only (no throw in impl) | Declaration only | Symbol identical, no new deps | **COMPATIBLE** |
| Remove `noexcept` + add `throw` in impl | Declaration + implementation | New `GLIBCXX_3.4.21` VERNEED | **BREAKING** |

**This example is scenario 2.** If you want to demonstrate noexcept removal without
introducing new library dependencies, use a noexcept impl in v2 that simply omits
the specifier but never throws.

## What abidiff misses

`abidiff` compares DWARF type information and symbol tables. It does not track
`DT_VERNEED` differences or new GLIBCXX symbol version requirements introduced by
implementation changes.

## Why ABICC may catch it differently

ABICC with the `abi-dumper` workflow (proper DWARF-based diff) may detect the new
exception-throwing path through the `__cxa_throw`/`GLIBCXX_3.4.21` dependency.
The legacy XML mode typically misses it.

## Code diff

```diff
-void Buffer::reset() noexcept {
+void Buffer::reset() {
     for (int i = 0; i < size_; ++i)
         data_[i] = 0;
+    throw std::runtime_error("reset failed");
 }
```

## Reproduce steps

```bash
cd examples/case15_noexcept_change
g++ -std=c++17 -shared -fPIC -g v1.cpp -o libv1.so
g++ -std=c++17 -shared -fPIC -g v2.cpp -o libv2.so

# Check VERNEED difference
objdump -p libv1.so | grep GLIBCXX   # → only GLIBCXX_3.4
objdump -p libv2.so | grep GLIBCXX   # → GLIBCXX_3.4 + GLIBCXX_3.4.21

# abicheck detects the new version requirement
abicheck dump libv1.so -o v1.json
abicheck dump libv2.so -o v2.json
abicheck compare v1.json v2.json    # → BREAKING: symbol_version_required_added
```
