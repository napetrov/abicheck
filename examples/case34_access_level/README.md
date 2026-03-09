# Case 34 -- Access Level Change

**abicheck verdict: SOURCE_BREAK**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `helper()` and `cache` are **public**; `internal_init()` is **protected** |
| v2 | `helper()` and `cache` moved to **private**; `internal_init()` promoted to **public** |

## Why this is NOT a binary ABI break

C++ access specifiers (`public`, `private`, `protected`) are enforced only at
compile time. They do not affect name mangling, symbol visibility, vtable layout,
or object layout (within the same access-specifier group ordering). A binary
compiled against v1 that calls `helper()` or accesses `cache` will continue to
work at runtime with v2's shared library -- the dynamic linker resolves symbols
by mangled name, not by access level.

However, any **new** code compiled against v2's header will fail to compile if it
tries to call `helper()` or access `cache` directly. This makes it a source-level
break but not a binary ABI break.

## Code diff

```diff
 class Widget {
 public:
     void render();
-    void helper();          // public
-    int cache;              // public
-
-protected:
-    void internal_init();   // protected
+    void internal_init();   // promoted from protected
+
+private:
+    void helper();          // was public, now private
+    int cache;              // was public, now private
 };
```

## Real Failure Demo

**Severity: SOURCE_BREAK (binary compatible)**

```bash
# Build v1 lib + app
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -g app.cpp -I. -L. -lv1 -Wl,-rpath,. -o app
./app
# -> render() called OK
# -> helper() called OK
# -> cache = 123

# Swap to v2 .so (do NOT recompile app)
g++ -shared -fPIC -g v2.cpp -o libv1.so
./app
# -> render() called OK
# -> helper() called OK        <-- still works! access is compile-time only
# -> cache = 123               <-- still works!

# But recompiling against v2 header FAILS:
g++ -g app.cpp -I. -L. -lv1 -Wl,-rpath,. -o app -include v2.hpp
# -> error: 'void Widget::helper()' is private within this context
```

**Why SOURCE_BREAK:** Existing binaries are unaffected, but new compilations against
the v2 header will fail. The ABI (binary layout, mangled names) is unchanged.
