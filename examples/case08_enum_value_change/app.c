#include "v1.h"
#include <stdio.h>

int main(void) {
    /* Compiled with v1: GREEN=1. get_signal() should return GREEN. */
    Color c = get_signal();
    if ((int)c == 1)
        printf("GREEN (correct)\n");
    else
        printf("ERROR: expected GREEN=1, got %d\n", (int)c);
    return 0;
}
