# Case 43: Base Class Member Added

**Category:** C++ Layout | **Verdict:** 🔴 BREAKING

## What breaks
A data member (`int extra_field`) is added to `Base`. Because `Derived` inherits from
`Base`, all fields declared in `Derived` are pushed to higher offsets — `Derived::value`
shifts by 4 bytes. Any code compiled against v1 that reads or writes `Derived::value`
through a v2 `.so` will access the wrong memory location.

The change propagates silently: the mangled symbol for `Derived::process()` is
unchanged, so `nm` and simple symbol checks show no breakage. Only a layout-aware
tool catches it.

## Why abidiff catches it
abidiff reads DWARF debug info and detects that `sizeof(Base)` grew and that
`Derived::value`'s byte offset changed. It reports:

- `TYPE_SIZE_CHANGED` on `Base` (8 → 12 bytes)
- `TYPE_FIELD_OFFSET_CHANGED` on `Derived::value` (offset 8 → 12)
- Exit code **4** (ABI change detected, non-symbol-removal break)

## Code diff

| v1.hpp | v2.hpp |
|--------|--------|
| `class Base { int base_id; virtual void describe(); };` | `class Base { int base_id; int extra_field; virtual void describe(); };` |
| `class Derived : public Base { int value; void process(); };` | *(layout shifts — `value` now at offset +12 instead of +8)* |

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build old library + app
g++ -shared -fPIC -g v1.cpp -o libv1.so
# (app.cpp reads Derived::value using v1 offsets)
g++ -g -I. app.cpp -L. -lv1 -Wl,-rpath,. -o app
./app
# → value = 42  (correct)

# Swap in new library (no recompile)
g++ -shared -fPIC -g v2.cpp -o libv1.so
./app
# → value = <garbage>  (reads extra_field or padding instead of value)
# → or: SIGSEGV if object is stack-allocated by caller
```

**Why CRITICAL:** The `this`-pointer arithmetic baked into the caller's object code
uses the old field offset. With v2, the same byte offset belongs to `extra_field`;
`value` is four bytes further. No runtime error is raised — the program continues
with a silently wrong value, leading to data corruption or hard-to-reproduce crashes.

## Reproduce manually
```bash
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -shared -fPIC -g v2.cpp -o libv2.so
abidw --out-file v1.xml libv1.so
abidw --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 4
```

## How to fix
Never add data members to a base class once the library is released. Alternatives:

1. **Pimpl in Base** — put all implementation state in a `BaseImpl* pImpl_` pointer.
   Adding members to `BaseImpl` is transparent to derived classes.
2. **Reserve padding** — add `char _reserved[N]` at the end of `Base` to absorb
   future members without shifting derived-class layouts (common in stable C++ ABIs).
3. **New derived class** — introduce `EnhancedBase : Base` with the extra field;
   existing `Derived` keeps its layout.
4. **SONAME bump** — if the addition is unavoidable, bump the major version
   (`libfoo.so.2`) and force recompilation of all consumers.
