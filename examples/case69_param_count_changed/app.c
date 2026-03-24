#include "v1.h"
#include <stdio.h>

int main(void) {
    /* Compiled against v1: transform(double, double) */
    double result = transform(3.0, 4.0);
    printf("transform(3.0, 4.0) = %.1f\n", result);
    printf("Expected: 10.0\n");
    return 0;
}
