/* case46: Pointer chain — pointed-to type changes through indirection levels
 *
 * A function returns int** (pointer to pointer). The ultimate pointee type
 * changes from int to long. Even though it's behind two levels of indirection,
 * callers that dereference the chain get wrong values on 32-bit platforms.
 *
 * BREAKING: FUNC_RETURN_CHANGED, PARAM_POINTER_LEVEL_CHANGED
 * libabigail equivalent: Function_Return_Type_Change (indirect)
 */
#ifndef CASE46_V1_H
#define CASE46_V1_H

int **get_matrix_row(int row);
void  set_cell(int **matrix, int row, int col, int val);
int   sum_row(int *const *matrix, int row, int cols);

#endif
