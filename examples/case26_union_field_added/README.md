# Case 26 — Union Field Added

**abicheck verdict: COMPATIBLE (informational/warning)**

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `union Value { int i; float f; };` |
| v2 | `union Value { int i; float f; double d; };` |

## Why this is NOT a binary ABI break

All union fields share offset 0. Adding a new field (`double d`) does not change
how existing fields (`int i`, `float f`) are accessed — their offset and
interpretation remain identical.

abicheck classifies this as **COMPATIBLE** because:
- Existing fields are unaffected (all at offset 0).
- No symbol resolution or calling convention change occurs.
- If the new field increases the union's overall size (e.g., `sizeof(double) > sizeof(float)`),
  that size change is caught separately by `TYPE_SIZE_CHANGED` (which IS breaking).

## What it does affect

- **Union size**: if the new field is the largest member, `sizeof(union Value)`
  increases. This is a genuine ABI concern but is detected as a separate
  `TYPE_SIZE_CHANGED` check.
- **Semantic contract**: new code paths may use the `double d` variant. Old consumers
  that interpret the raw storage differently are unaffected as long as they only
  access their known fields.

## Contrast with BREAKING union changes

| Change | Verdict | Why |
|---|---|---|
| Field **added** | COMPATIBLE | Existing fields at offset 0 unchanged |
| Field **removed** | BREAKING | Removes a valid representation |
| Field **type changed** | BREAKING | Reinterpretation of shared storage |
| Size changed (from field addition) | BREAKING | Caught separately by TYPE_SIZE_CHANGED |

## Code diff

```diff
 union Value {
     int i;
     float f;
+    double d;
 };
```
