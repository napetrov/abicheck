# Case 20 — Enum Member Value Changed

**abicheck verdict: BREAKING**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `enum ErrorCode { OK = 0, ERROR = 1 };` |
| v2 | `enum ErrorCode { OK = 0, ERROR = 99 };` |

## What breaks at binary level

Changing the numeric value of an enum member is a **semantic ABI break**. Existing
binaries were compiled with `ERROR = 1` and will pass, store, and compare that value.
The new library interprets `ERROR` as `99` — the same symbolic name now maps to a
different integer.

This is effectively a protocol rewrite without version negotiation. Components built
against different versions will exchange the same integer and interpret it with
opposite semantics.

## Consumer impact

```c
/* consumer compiled against v1 */
if (result == ERROR) { /* ERROR = 1 */ }

/* with v2 library, ERROR = 99 */
/* consumer checks for value 1, library returns 99 */
/* error condition is silently missed */
```

## Mitigation

- Never reassign released enum numeric values.
- Append new constants instead of renumbering.
- Introduce explicit protocol versioning for cross-version communication.

## Code diff

```diff
-enum ErrorCode { OK = 0, ERROR = 1 };
+enum ErrorCode { OK = 0, ERROR = 99 };
```
