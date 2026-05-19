# case74 — internal `detail::` base class layout change leaks via public API

**Verdict:** BREAKING
**Kind:** `type_size_changed` (on `mylib::detail::descriptor_base`) + new
`internal_type_leaks_via_public_api` (synthetic finding emphasising the leak)

## Pattern

The library declares its "internal" implementation helpers inside a
`detail::` namespace, matching the convention used by oneDAL, oneTBB,
many Boost libraries, and the standard library's `std::__detail`:

```cpp
namespace mylib::detail {
    class descriptor_base { /* ... */ };
}
class knn_descriptor : public detail::descriptor_base { /* ... */ };
```

v2 adds an `int max_iter_` member to `detail::descriptor_base`. From the
library author's perspective this is purely an internal change. From
consumers' perspective it's a binary ABI break:

- `sizeof(knn_descriptor)` increased by 4–8 bytes (alignment-dependent).
- Field offsets of `neighbor_count_` and the vtable pointer (if any) shifted.
- Stack-allocated `knn_descriptor` instances overflow.
- Heap-allocated objects from callers compiled against v1 headers can underallocate when run against v2 binaries.

## Why this case exists

This is the **textbook scenario** that motivates the
`INTERNAL_TYPE_LEAKS_VIA_PUBLIC_API` change kind. Existing detectors
already report `type_size_changed` on `detail::descriptor_base`, but
without a leak-path overlay it's easy for a reviewer to dismiss the
finding as "internal-only". The leak overlay states the reachability
chain `knn_descriptor → base:detail::descriptor_base` so the
implication for the public class is impossible to miss.
