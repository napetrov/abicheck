# Case 116: _Atomic qualifier added (C11)

**Category:** Binary ABI break / C11 | **Verdict:** 🔴 BREAKING

## What changed

`v1` exposes a `Buffer` struct with a plain `int refcount` and a
`buffer_count()` returning `int`. `v2` adds the C11 `_Atomic` qualifier to both
the field and the return type.

Per WG14, the size and alignment of an `_Atomic`-qualified type may differ from
the unqualified type and varies across implementations (some lock-free types
carry extra padding/alignment). So the `Buffer` layout and the return-value ABI
can diverge: a consumer built against v1 reads the field at the wrong
offset/width and interprets the return with the wrong representation.

## How abicheck catches it

`atomic_qualifier_changed` fires for each public slot (parameter, return, or
field) where the `_Atomic` qualifier is added or removed. Layout-level findings
(`type_size_changed` / `struct_field_*`) may also appear; the specialised kind
names the `_Atomic` root cause.

## Files
- `v1.h` / `v2.h` — plain vs `_Atomic` declarations
- `v1.c` / `v2.c` — the two library builds
- `app.c` — consumer built against the plain interface
