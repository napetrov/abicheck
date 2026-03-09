# Case 21 — Method Became Static

**abicheck verdict: BREAKING**

## What changes

| Version | Declaration |
|---------|-----------|
| v1 | `class Widget { void bar(); };` |
| v2 | `class Widget { static void bar(); };` |

## What breaks at binary level

In the Itanium C++ ABI, **`static`-ness is NOT encoded in the mangled symbol name** —
only explicit parameters are. `Widget::bar()` and `static Widget::bar()` both mangle
to `_ZN6Widget3barEv`. The linker resolves the same symbol in both cases.

The break is a **calling convention mismatch**:
- Instance method: caller passes implicit `this` pointer in `%rdi` (first register argument).
- Static method: no `this` expected — `%rdi` holds the first explicit argument (none here) or is ignored.

Existing binaries compiled against v1 still link successfully against v2 (same symbol name).
However, they pass a garbage `this` value in `%rdi` to a function that doesn't expect it.
For a void no-arg method like `bar()`, the function simply ignores `%rdi` — resulting in
**silent success** rather than a crash. The UB is real but may be invisible without UBSAN.

This is a **calling convention ABI break**: the calling convention is wrong, and any method
that reads `this` through the implicit parameter would behave incorrectly.

> **Note:** Because the mangled name is identical, `abidiff` **cannot detect this change**
> — it sees the same symbol in both `.so` files. This is a known blind spot. ABICC
> catches it via header AST comparison.

## Consumer impact

```cpp
/* consumer compiled against v1 */
Widget w;
w.bar();  /* emits call with implicit 'this' pointer */

/* with v2: Widget::bar() is static — no 'this' expected */
/* call convention mismatch → undefined behavior or crash */
```

## Mitigation

- Add the static helper under a new name; preserve the old member method.
- If migration is needed, deprecate the old method and provide both during a
  transition period.

## Code diff

```diff
 class Widget {
 public:
-    void bar();
+    static void bar();
 };
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** app compiled against old header (instance `bar()`) links against new lib where `bar()` is static. The symbol resolves (same mangled name), but `this` is passed as a garbage argument in `%rdi`.

```bash
# Build old lib + app
g++ -shared -fPIC -g old/lib.cpp -Iold -o libwidget.so
g++ -g app.cpp -Iold -L. -lwidget -Wl,-rpath,. -o app
./app
# → bar() called (instance method)

# Swap in new lib (static bar() — same symbol name _ZN6Widget3barEv)
g++ -shared -fPIC -g new/lib.cpp -Inew -o libwidget.so
./app
# → bar() called (static method)  ← links and runs, but with UB
# (this pointer passed in %rdi is ignored by static bar(); any method
#  that uses 'this' internals would read garbage or crash)

# Detect with UBSan (note: for void no-arg bar(), UBSan may be silent since
# the function doesn't dereference 'this'; use a method that accesses members):
g++ -shared -fPIC -g -fsanitize=undefined new/lib.cpp -Inew -o libwidget.so
g++ -g -fsanitize=undefined app.cpp -Iold -L. -lwidget -Wl,-rpath,. -o app_ub
./app_ub
# → bar() called (static method)  ← may be silent for void no-arg methods
# For methods that access 'this->member', UBSan reports:
# → runtime error: member call on address ... which does not point to an object
```

**Why CRITICAL:** The `static`-ness change does NOT change the mangled name (Itanium C++ ABI
does not encode static-ness). The binary links and appears to run. However, the calling
convention is wrong — old callers pass `this` in `%rdi` which the new static function ignores.
For methods that access member state through `this`, this is silent memory corruption.
