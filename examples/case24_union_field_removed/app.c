#include "old/lib.h"
#include <stdio.h>

int main(void) {
    union Data d;
    init_data(&d);
    /* v1: d.f = 3.14, v2: d.i = 42 (float interpretation of 42 = garbage) */
    printf("d.f = %e (expected 3.14, got wrong value with v2)\n", d.f);
    return 0;
}
