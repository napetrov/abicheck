# Case 21 — Method Became Static

**abicheck verdict: BREAKING**

## What changes

| Version | Declaration |
|---------|-----------|
| v1 | `class Widget { void bar(); };` |
| v2 | `class Widget { static void bar(); };` |

## What breaks at binary level

In the Itanium C++ ABI, static and instance methods have different calling conventions.
An instance method receives an implicit `this` pointer as the first argument; a static
method does not. Changing a method from instance to static (or vice versa) changes:

1. **The mangled symbol name** — callers compiled against v1 look up one symbol; v2
   exports a different one.
2. **The calling convention** — even if the symbol somehow resolved, the argument
   positions in registers/stack would be wrong.

This is a **hard ABI break**: existing binaries fail to bind or invoke the function
correctly.

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

**Scenario:** app compiled against old header (instance `bar()`) links against new lib where `bar()` is static — mangled name change causes linker failure.

```bash
# Build old lib + app
g++ -shared -fPIC -g old/lib.cpp -Iold -o libwidget.so
g++ -g app.cpp -Iold -L. -lwidget -Wl,-rpath,. -o app
./app
# → bar() called (instance method)

# Swap in new lib (static bar())
g++ -shared -fPIC -g new/lib.cpp -Inew -o libwidget.so
./app
# → ./app: symbol lookup error: undefined symbol: _ZN6Widget3barEv
# (or wrong 'this' pointer passed if symbol happens to resolve)
```

**Why CRITICAL:** In the Itanium C++ ABI, removing `static` changes the mangled name
and calling convention (instance method passes implicit `this`; static does not).
The dynamic linker cannot resolve the old symbol, or if it does, the `this` pointer
is passed as a garbage first argument.
