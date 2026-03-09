#include "v1.h"
#include <stdio.h>

int main(void) {
    /* Compiled against v1: process(int a, int b) → a+b as double */
    double result = process(3, 4);
    printf("process(3, 4) = %.1f\n", result);
    printf("Expected: 7.0\n");
    return 0;
}
