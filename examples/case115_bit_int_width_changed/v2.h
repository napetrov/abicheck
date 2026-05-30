#pragma once
/* v2: the accumulator widened to _BitInt(256). The storage size and the
   calling-convention treatment of the parameter/return change. */

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    _BitInt(256) acc;
} Accumulator;

void acc_add(Accumulator *a, _BitInt(256) delta);
_BitInt(256) acc_value(const Accumulator *a);

#ifdef __cplusplus
}
#endif
