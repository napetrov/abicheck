# Case 38: Virtual Method Changes

**Category:** C++ Virtual / Deleted | **Verdict:** BREAKING

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `transform()` is non-virtual; `validate()` is virtual; `execute()` is virtual; copy ctor is user-defined |
| v2 | `transform()` becomes virtual; `validate()` loses virtual; `execute()` becomes pure virtual (`= 0`); copy ctor is `= delete` |

## Why this is a binary ABI break

Each change corrupts the vtable layout that existing binaries were compiled against:

1. **`transform()` became virtual** — a new vtable slot is inserted. The class gains a vptr if it didn't already have one at that offset, and existing vtable indices shift.
2. **`validate()` lost virtual** — the vtable slot is removed. Old binaries dispatching through the vtable at the old index now call the wrong function or dereference garbage.
3. **`execute()` became pure virtual** — the vtable slot now points to `__cxa_pure_virtual`. Any old binary that instantiates `Processor` directly (which was legal in v1) will segfault when calling `execute()`.
4. **Copy ctor deleted** — old binaries that were linked against the copy constructor symbol will get an undefined symbol error at load time.

## Code diff

```diff
 class Processor {
 public:
-    void transform(int data);
+    virtual void transform(int data);

-    virtual void validate(int data);
+    void validate(int data);

-    virtual void execute();
+    virtual void execute() = 0;

-    Processor(const Processor &other);
+    Processor(const Processor &other) = delete;

     Processor() = default;
     virtual ~Processor() = default;
 };
```

## Real Failure Demo

**Severity: CRITICAL**

**Scenario:** compile app against v1, swap in v2 `.so` without recompile.

```bash
# Build v1 lib + app
g++ -shared -fPIC -g v1.cpp -o libprocessor.so
g++ -g app.cpp -I. -L. -lprocessor -Wl,-rpath,. -o app
./app
# → Calling transform(42)...
# → Calling validate(10)...
# → Calling execute()...
# → MyProcessor::execute() called
# → Copying processor...
# → Copy created successfully

# Swap to v2 (no recompile of app)
g++ -shared -fPIC -g v2.cpp -o libprocessor.so
./app
# → undefined symbol / segfault / vtable corruption
# The copy ctor symbol is gone → immediate load failure.
# If that were resolved, vtable slot indices are wrong →
# calling validate() dispatches to the wrong function,
# and execute() may call __cxa_pure_virtual → abort.
```

**Why CRITICAL:** Vtable layout is baked into the calling binary at compile time. Any
change to the number or order of virtual methods silently corrupts dispatch. The deleted
copy constructor removes a symbol entirely, causing immediate load failure.

## Reproduce manually
```bash
g++ -shared -fPIC -g v1.cpp -o libv1.so
g++ -shared -fPIC -g v2.cpp -o libv2.so
abidw --out-file v1.xml libv1.so
abidw --out-file v2.xml libv2.so
abidiff v1.xml v2.xml
echo "exit: $?"   # → 12 (ABI change + breaking)
```

## How to fix
Never change the virtual-ness of existing methods in a stable ABI. To add new virtual
methods, append them (do not reorder), and bump the SONAME. Pure virtual additions
require a major version bump since they break all existing concrete subclasses.
