# Case 26b — Union Field Added (No Size Change)

**Verdict:** 🟢 COMPATIBLE

## What changes

| Version | Definition |
|---------|-----------|
| v1 | `union Value { long l; double d; };` |
| v2 | `union Value { long l; double d; int i; };` |

## Why this is NOT a binary ABI break

Adding `int i` does **not** change `sizeof(union Value)`:
- v1: `sizeof = max(sizeof(long)=8, sizeof(double)=8) = 8 bytes`
- v2: `sizeof = max(sizeof(long)=8, sizeof(double)=8, sizeof(int)=4) = 8 bytes`

All existing fields remain at offset 0 with identical sizes and types.
Old callers allocate exactly the right amount of memory for v2 as well.
No struct embeddings or array strides are affected.

## Contrast with case26

| Case | Field added | sizeof change | Verdict |
|------|-------------|---------------|---------|
| case26 | `double d` added to `{int i; float f}` | 4 → 8 bytes | BREAKING (TYPE_SIZE_CHANGED) |
| case26b | `int i` added to `{long l; double d}` | 8 → 8 bytes | COMPATIBLE |

## Code diff

```diff
 union Value {
     long   l;
     double d;
+    int    i;   /* sizeof stays 8: smaller than double — COMPATIBLE */
 };
```

## Runtime Demo

```bash
# Build libs + app compiled against v1
make all

# Run with v1 lib — baseline
./app_v1
# → after fill: v.l = 42
# → OK: union field added (no size change) is ABI-compatible

# Swap to v2 (old binary, new lib — sizeof unchanged)
make test-compat
# → after fill: v.l = 42   ← identical result
# → EXIT:0                  ← app exits cleanly: COMPATIBLE
```

## abicheck output

abicheck detects **no TYPE_SIZE_CHANGED** (sizeof stays 8 bytes).
The added `int i` field appears as a new union member — informational only.
Verdict: **COMPATIBLE**.
