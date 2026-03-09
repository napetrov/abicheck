#include "v1.h"
#include <stdio.h>

int main(void) {
    /* v1 ABI: get_count() returns int */
    int n = get_count();
    printf("get_count() = %d\n", n);
    /* v1: prints 42; v2 (returns 3000000000L): prints -1294967296 (truncated) */
    return 0;
}
