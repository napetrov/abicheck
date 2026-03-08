# Case 23 — Virtual Method Became Pure Virtual

**abicheck verdict: BREAKING**

## What changes

| Version | Declaration |
|---------|-----------|
| v1 | `class Processor { virtual void process(); };` |
| v2 | `class Processor { virtual void process() = 0; };` |

## What breaks at binary level

Making a virtual method pure (`= 0`) has two ABI consequences:

1. **The class becomes abstract** — existing code that directly instantiates
   `Processor` objects (e.g., `new Processor()`) will fail. While this is primarily
   a compile-time issue, it breaks binary compatibility for plugins or modules that
   were compiled to instantiate the class directly.

2. **vtable layout changes** — the vtable entry for `process()` becomes a pure-call
   stub (typically `__cxa_pure_virtual`). If existing compiled code calls through the
   vtable, it hits the pure-call handler instead of the concrete implementation.

## Consumer impact

```cpp
/* consumer compiled against v1 (concrete class) */
Processor* p = new Processor();
p->process();  /* calls concrete implementation */

/* with v2: Processor is abstract */
/* vtable slot points to __cxa_pure_virtual */
/* → runtime abort: "pure virtual method called" */
```

For plugin architectures where downstream code `extends` the interface:

```cpp
/* old plugin implements only process() */
struct MyPlugin : Processor {
    void process() override;
};
/* this still works — but any new pure virtual methods
   added to Processor would break existing plugins */
```

## Mitigation

- Create `Processor2` (or `IProcessor`) as the new abstract interface.
- Keep the original `Processor` class frozen for existing consumers.
- Version plugin interfaces explicitly.

## Code diff

```diff
 class Processor {
 public:
-    virtual void process();
+    virtual void process() = 0;
 };
```
