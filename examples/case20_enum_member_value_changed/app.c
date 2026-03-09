#include "old/lib.h"
#include <stdio.h>

int get_result(void);

int main(void) {
    int r = get_result();
    if (r == ERROR)
        printf("Error detected (correct)\n");   /* ERROR=1 in v1 */
    else
        printf("No error? Got %d - WRONG! (v2 changed ERROR to 99)\n", r);
    return 0;
}
