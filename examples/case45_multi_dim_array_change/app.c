#include "v1.h"
#include <stdio.h>

int main(void) {
    Matrix m = {0};
    m.rows = ROWS;
    m.cols = COLS;

    matrix_set(&m, 0, 0, 1.5f);
    matrix_set(&m, 0, 1, 2.5f);

    float a = matrix_get(&m, 0, 0);
    float b = matrix_get(&m, 0, 1);
    float sum = a + b;

    printf("sum = %.3f\n", sum);
    printf("expected = 4.000\n");

    if (sum < 3.999f || sum > 4.001f) {
        printf("CORRUPTION: matrix element type/layout changed (float[][] vs double[][])\n");
        return 1;
    }
    return 0;
}
