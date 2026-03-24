# Case 72: Covariant Return Type Changed

**Category:** VTable / Inheritance | **Verdict:** BREAKING

## What breaks

The class hierarchy changes: a new intermediate class `Drawable` is inserted
between `Shape` and `Circle`. This causes `Circle::clone()` to change its
covariant return type from `Circle*` to `Drawable*`.

Under the Itanium C++ ABI, covariant return types require **vtable thunks** —
small code fragments that adjust the `this` pointer when converting between base
and derived return types. When the covariant return type changes:

1. The vtable thunk entry for `clone()` must adjust to a different offset
2. The vtable layout changes due to the new base class `Drawable`
3. Old binaries with stale vtables dispatch through the wrong thunk, applying
   incorrect pointer adjustments

This is fundamentally different from case09 (vtable reorder), case23 (pure virtual
added), case38 (virtual methods changed), and case68 (virtual method added). Those
change **which** slot is called; this case changes the **thunk adjustment** within
a slot that still nominally exists. The break is in the pointer arithmetic, not
the dispatch target.

## Why abicheck catches it

Type comparison detects the base class hierarchy change (`type_base_changed`) and
the vtable layout change (`type_vtable_changed`). The function return type change
from `Circle*` to `Drawable*` is also detected (`func_return_changed`).

## Code diff

```cpp
// v1: flat hierarchy
class Circle : public Shape {
    Circle *clone() const override;  // covariant: returns Circle*
};

// v2: intermediate class inserted, covariant return changes
class Drawable : public Shape { /* new */ };
class Circle : public Drawable {
    Drawable *clone() const override;  // covariant: returns Drawable*
};
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 and app
g++ -shared -fPIC -g v1.cpp -o libshape.so
g++ -g app.cpp -L. -lshape -Wl,-rpath,. -o app
./app
# -> clone radius = 5
# -> Expected: 5
# -> clone area = 75
# -> Expected: 75

# Build v2 (hierarchy changed, covariant return changed)
g++ -shared -fPIC -g v2.cpp -o libshape.so
./app
# -> crash or garbage (vtable thunk applies wrong pointer adjustment)
```

**Why CRITICAL:** The old binary's vtable for `Circle` was compiled with thunk
offsets for the `Shape → Circle` conversion. In v2, the hierarchy is
`Shape → Drawable → Circle`, requiring different adjustment offsets. The old
thunk applies the wrong offset to the returned pointer, yielding a misaligned
or out-of-bounds pointer. Calling any method on the returned object crashes or
corrupts memory.

## How to fix

Never insert classes into an existing hierarchy without bumping the SONAME.
If the hierarchy must evolve, use composition instead of inheritance:

```cpp
/* Safe: composition instead of hierarchy insertion */
class Circle : public Shape {
    Drawable drawable_;  /* has-a instead of is-a */
    Circle *clone() const override;  /* covariant return unchanged */
};
```

Or freeze the public hierarchy and use internal delegation:

```cpp
/* Preserve public ABI, change implementation */
class Circle : public Shape {  /* public hierarchy frozen */
    Circle *clone() const override;
private:
    struct Impl;  /* internal hierarchy changes hidden */
    Impl *impl_;
};
```

## Real-world example

Qt's class hierarchy is carefully designed to never insert intermediate classes
in public hierarchies. The KDE Binary Compatibility policy explicitly forbids
this. The COM/XPCOM interface model avoids this entirely by using flat interface
inheritance. LLVM's RTTI system (`isa<>`, `dyn_cast<>`) would break if class
hierarchies changed because the classof() chain encodes the exact hierarchy.

## References

- [Itanium C++ ABI §2.5.3: Virtual Covariant Thunks](https://itanium-cxx-abi.github.io/cxx-abi/abi.html#vtable-general)
- [KDE: Binary Compatibility — Do not add base classes](https://community.kde.org/Policies/Binary_Compatibility_Issues_With_C%2B%2B)
