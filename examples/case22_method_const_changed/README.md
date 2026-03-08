# Case 22 — Method Const Qualifier Changed

**abicheck verdict: BREAKING**

## What changes

| Version | Declaration |
|---------|-----------|
| v1 | `class Widget { void get() const; };` |
| v2 | `class Widget { void get(); };` |

## What breaks at binary level

In the Itanium C++ ABI, `const` qualification on a member function is part of the
mangled symbol name:

- `Widget::get() const` → `_ZNK6Widget3getEv` (note the `K` for const)
- `Widget::get()`       → `_ZN6Widget3getEv`

Removing (or adding) `const` produces a **different mangled name**. Existing binaries
compiled against v1 import `_ZNK6Widget3getEv`, but v2 only exports `_ZN6Widget3getEv`.
The dynamic linker cannot resolve the symbol → **unresolved symbol error at load time**.

## Consumer impact

```cpp
/* consumer compiled against v1 */
const Widget& w = get_widget();
w.get();  /* calls _ZNK6Widget3getEv */

/* v2 library exports _ZN6Widget3getEv (non-const) */
/* → undefined symbol: _ZNK6Widget3getEv */
```

## Mitigation

- Keep the old const-qualified method and add a non-const overload if needed.
- Provide both signatures during a transition period.

## Code diff

```diff
 class Widget {
 public:
-    void get() const;
+    void get();
 };
```
