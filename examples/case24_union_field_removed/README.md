# Case 24 — Union Field Removed

**abicheck verdict: BREAKING**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `union Data { int i; float f; };` |
| v2 | `union Data { int i; };` |

## What breaks at binary level

Removing a union field removes a supported representation of the shared storage.
While the remaining field (`int i`) is still at offset 0 and accessible, any code
that was compiled to use the `float f` variant is now accessing an undefined member.

If the removal also reduces the union's size (e.g., removing a `double` field from
a union of `int` and `double`), existing code that allocates `sizeof(union Data)` with
the old size will over-allocate (harmless) or under-allocate if the field was the
largest member (harmful — but this is caught by `TYPE_SIZE_CHANGED`).

The semantic break is the main concern: the removed field was part of the type's
public contract, and consumers relied on it as a valid interpretation.

**Note:** Adding a union field is classified as **COMPATIBLE** because all fields
share offset 0 and existing fields are unaffected. Size increases are caught
separately.

## Consumer impact

```c
/* consumer compiled against v1 */
union Data d;
d.f = 3.14f;   /* valid in v1 */
lib_consume(d); /* library no longer expects float variant */

/* v2: 'f' field doesn't exist — semantic mismatch */
```

## Mitigation

- Keep union variants stable across ABI-compatible releases.
- Introduce versioned replacement types (e.g., `DataV2`) when the union contract
  must change.
- Use tagged unions with explicit discriminators to manage variant evolution.

## Code diff

```diff
-union Data { int i; float f; };
+union Data { int i; };
```
