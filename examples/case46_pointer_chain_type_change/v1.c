#include "v1.h"
#include <stdlib.h>
static int storage[4][4];
int **get_matrix_row(int row) { return (int **)&storage[row]; }
void  set_cell(int **matrix, int row, int col, int val) { matrix[row][col] = val; }
int   sum_row(int *const *matrix, int row, int cols) {
    int s = 0; for (int c = 0; c < cols; c++) s += matrix[row][c]; return s;
}
