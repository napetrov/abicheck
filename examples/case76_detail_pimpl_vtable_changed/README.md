# case76 — internal `detail::` polymorphic base vtable change

**Verdict:** BREAKING
**Kinds:** `type_vtable_changed` / `func_virtual_added` on
`mylib::detail::algorithm_iface`, plus
`internal_type_leaks_via_public_api`.

## Pattern

```cpp
namespace mylib::detail { class algorithm_iface { virtual int run() = 0; virtual int status() const = 0; }; }
class svm_algorithm : public detail::algorithm_iface { /* ... */ };
```

v2 inserts `virtual int progress()` between `run()` and `status()` in
`detail::algorithm_iface`. The vtable layout shifts:

| Slot | v1                   | v2                     |
| ---- | -------------------- | ---------------------- |
| 0    | `~algorithm_iface()` | `~algorithm_iface()`   |
| 1    | `run()`              | `run()`                |
| 2    | `status()`           | `progress()`           |
| 3    | —                    | `status()`             |

A v1-compiled consumer that calls `status()` now dispatches to the
slot occupied by `progress()` — wrong return value at best, crash at
worst.

The leak overlay reports the reachability chain
`mylib::svm_algorithm → base:detail::algorithm_iface` so reviewers
see that the "internal" vtable change is in fact part of the public ABI.
