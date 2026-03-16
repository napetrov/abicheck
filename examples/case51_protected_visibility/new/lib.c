#include "lib.h"

/* PROTECTED visibility — exported but NOT interposable.
   The library's own calls to hook_point() always use this definition,
   even if another .so or LD_PRELOAD provides a GLOBAL hook_point. */
__attribute__((visibility("protected")))
int hook_point(int x) { return x * 2; }

int compute(int x) { return hook_point(x) + 1; }
