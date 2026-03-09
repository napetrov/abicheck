#include "old/lib.h"
#include <stdio.h>

int main(void) {
    union Value v;
    fill(&v);
    printf("v.i = %d (expected 42)\n", v.i);
    return 0;
}
