# Case 19 — Enum Member Removed

**abicheck verdict: BREAKING**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `enum Status { OK = 0, ERROR = 1, FOO = 2 };` |
| v2 | `enum Status { OK = 0, ERROR = 1 };` |

## What breaks at binary level

Removing an enum member invalidates any code that uses that member's numeric value.
Existing binaries that were compiled with `FOO = 2` may store, transmit, or switch on
that value. The new library no longer defines that value as a valid member of the enum.

This is a **semantic ABI break**: while the remaining values (`OK`, `ERROR`) are still
at the same numeric positions, the removed value `FOO = 2` becomes undefined in the
new version. Persisted data, protocol messages, or configuration files that contain
the removed value will be misinterpreted.

## Consumer impact

```c
/* consumer compiled against v1 */
enum Status s = FOO;  /* s = 2 */
write_to_file(s);

/* later, same consumer reads back value 2 with v2 library */
/* library has no FOO — value 2 is undefined behavior */
```

## Mitigation

- Never remove released enum members; mark them as deprecated instead.
- Map legacy values deliberately in deserialization/protocol handling.
- Use explicit sentinel values (e.g., `STATUS_MAX`) to define valid ranges.

## Code diff

```diff
-enum Status { OK = 0, ERROR = 1, FOO = 2 };
+enum Status { OK = 0, ERROR = 1 };
```
