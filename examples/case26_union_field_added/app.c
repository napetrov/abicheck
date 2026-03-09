#include "old/lib.h"
#include <stdio.h>

int main(void) {
    union Value v;
    v.i = 0;
    fill(&v);
    printf("after fill: v.i = %d\n", v.i);
    if (v.i == 42) {
        printf("unexpected old-compatible value\n");
        return 0;
    }
    printf("UNION_SIZE_MISMATCH: v2 wrote different representation (possible overflow with old layout)\n");
    return 2;
}
