#include "v2.h"
#include <stdlib.h>
static long storage[4][4];
long **get_matrix_row(int row) { return (long **)&storage[row]; }
void   set_cell(long **matrix, int row, int col, long val) { matrix[row][col] = val; }
long   sum_row(long *const *matrix, int row, int cols) {
    long s = 0; for (int c = 0; c < cols; c++) s += matrix[row][c]; return s;
}
