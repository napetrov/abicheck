/* case46 v2: pointer chain element type changed int→long — BREAKING */
#ifndef CASE46_V2_H
#define CASE46_V2_H

long **get_matrix_row(int row);
void   set_cell(long **matrix, int row, int col, long val);
long   sum_row(long *const *matrix, int row, int cols);

#endif
