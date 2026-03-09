#include "v1.h"
#include <stdio.h>

int main(void) {
    /* v1 ABI: get_count() returns int — caller reads 32-bit value */
    int n = get_count();
    printf("Expected: 3000000000\n");
    printf("Got:      %d\n", n);
    return 0;
}
