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
| case26 | `double d` to `{int i; float f}` | 4 → 8 bytes | BREAKING (TYPE_SIZE_CHANGED) |
| case26b | `int i` to `{long l; double d}` | 8 → 8 bytes | COMPATIBLE |

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
# Build v1 lib + app
gcc -shared -fPIC -g -Iold -o libv1.so old/lib.c
gcc -g app.c -Iold -L. -lv1 -Wl,-rpath,. -o app_v1
./app_v1
# → after fill: v.l = 42
# → OK: union field added (no size change) is ABI-compatible

# Swap to v2 (int i added, sizeof unchanged)
gcc -shared -fPIC -g -Inew -o libv2.so new/lib.c
cp libv2.so libv1.so
./app_v1
# → after fill: v.l = 42   ← identical result: COMPATIBLE
```

## abicheck output

abicheck detects **no TYPE_SIZE_CHANGED** (sizeof stays 8 bytes).
The added `int i` field appears as a new union member — informational only.
Verdict: **COMPATIBLE**.
