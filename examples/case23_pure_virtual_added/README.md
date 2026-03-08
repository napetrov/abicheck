# Case 23 — Virtual Method Became Pure Virtual

**abicheck verdict: BREAKING**

## What changes

| Version | Declaration |
|---------|-----------|
| v1 | `class Processor { virtual void process(); };` |
| v2 | `class Processor { virtual void process() = 0; };` |

## What breaks at binary level

Making `Processor::process()` pure virtual (`= 0`) has two ABI consequences:

1. **The vtable entry for `process()` is replaced** — the slot that previously
   pointed to `Processor`'s concrete implementation of `process()` now points to
   the pure-call handler (`__cxa_pure_virtual`). Already-compiled consumers that
   invoke `process()` through a `Processor*` vtable dispatch will hit the pure-call
   handler at runtime, causing `std::terminate` instead of calling the old base
   implementation.

2. **`Processor` becomes abstract** — source-level rebuilds will fail to compile
   `new Processor()` (abstract class cannot be instantiated). For already-compiled
   binaries this is not the direct failure mode; the runtime break comes from point 1
   above (dispatch to the pure-call handler via the vtable slot).

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
