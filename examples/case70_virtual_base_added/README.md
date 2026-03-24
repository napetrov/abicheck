# Case 70: Virtual Base Class Added

**Category:** Class Layout | **Verdict:** BREAKING

## What breaks

The inheritance of `Widget` changes from non-virtual (`public Base`) to virtual
(`public virtual Base`). This fundamentally changes the object layout:

- **v1 layout:** `{vptr, base_val, widget_data}` (Base subobject at fixed offset)
- **v2 layout:** `{vptr, widget_data, vbase_ptr, [padding], base_val}` (Base subobject moved to end, accessed via vbase pointer)

Old binaries compiled against v1 expect `base_val` at a fixed offset from the
start of the object. In v2, the base subobject is relocated to the end of the
most-derived object and accessed indirectly through a virtual base table pointer.
Field accesses hit wrong memory locations.

This is distinct from case37 (base class type changed) and case60 (base class
order in multiple inheritance) because virtual inheritance introduces an entirely
different memory indirection mechanism.

## Why abicheck catches it

Type comparison detects that `Widget`'s inheritance changed from non-virtual to
virtual (`base_class_virtual_changed`). The class size and field offsets change,
which is flagged as BREAKING.

## Code diff

```cpp
// v1: non-virtual inheritance
class Widget : public Base {
    int widget_data;
};

// v2: virtual inheritance (inserts vbase pointer, relocates Base subobject)
class Widget : public virtual Base {
    int widget_data;
};
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 and app
g++ -shared -fPIC -g v1.cpp -o libwidget.so
g++ -g app.cpp -L. -lwidget -Wl,-rpath,. -o app
./app
# -> combined() = 30
# -> Expected: 30

# Build v2 (virtual inheritance)
g++ -shared -fPIC -g v2.cpp -o libwidget.so
./app
# -> combined() = <garbage or crash>
```

**Why CRITICAL:** The virtual base pointer changes sizeof(Widget) and shifts all
field offsets. Old code accesses `widget_data` and `base_val` at stale offsets,
reading garbage memory. With virtual inheritance, even the vtable dispatch
mechanism changes (virtual base offsets are stored in the vtable).

## How to fix

Virtual inheritance is a fundamental design choice that must be established from
the first version and never changed. If diamond inheritance support is needed
later, introduce a new class hierarchy alongside the old one:

```cpp
class Widget : public Base { /* keep original */ };
class VirtualWidget : public virtual Base { /* new hierarchy */ };
```

## Real-world example

The Itanium C++ ABI specification dedicates significant sections to virtual base
class handling. Qt's `QObject` hierarchy deliberately avoids virtual inheritance
to maintain ABI stability. The GCC and Clang ABI implementations handle virtual
bases differently in edge cases, making this change even more dangerous across
toolchains.

## References

- [Itanium C++ ABI -- Virtual Base Class Layout](https://itanium-cxx-abi.github.io/cxx-abi/abi.html#vtable-general)
- [KDE Policies: Binary Compatibility -- Never change virtual inheritance](https://community.kde.org/Policies/Binary_Compatibility_Issues_With_C%2B%2B)
