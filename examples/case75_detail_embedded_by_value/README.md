# case75 — internal `detail::` impl struct embedded by value

**Verdict:** BREAKING
**Kinds:** `struct_field_added` / `type_size_changed` on
`mylib::detail::table_impl`, plus `internal_type_leaks_via_public_api`.

## Pattern

```cpp
namespace mylib::detail { struct table_impl { /* ... */ }; }
class table { detail::table_impl impl_; };   // embedded by value
```

v2 adds `layout_kind` to `detail::table_impl`. Because `mylib::table`
embeds the impl by value (no pointer indirection), the size of the
public `table` class grows. Existing consumers that allocate, copy, or
pass `table` instances are broken.

## How the leak overlay reports it

After the existing `struct_field_added` finding on `detail::table_impl`,
the post-processor adds an `internal_type_leaks_via_public_api`
finding whose `description` cites the embedding path:

```text
mylib::table → field:impl_ → mylib::detail::table_impl
```

and notes the *embedded-by-value* severity hint (layout propagates,
not just identity).
