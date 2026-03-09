#include "v1.h"
#include <stdio.h>

int main(void) {
    struct Point p = make_point(10, 20);

    /* Access fields by v1 names: .x and .y
     * In v2 these are renamed to .col and .row, so this code
     * won't compile against v2.h. But the binary layout is
     * identical (same offsets, same types), so the already-compiled
     * binary works fine with v2's .so. */
    printf("p.x = %d\n", p.x);
    printf("p.y = %d\n", p.y);

    return 0;
}
