/* case28: typedef opaque / dim_t change demo
 * v1: dim_t = int  (get_dimension truncates 3000000000 to -1294967296)
 * v2: dim_t = long (get_dimension returns correct value 3000000000)
 *
 * The app prints the raw returned value. When run against v1 you see
 * truncation; when run against v2 you see the full value.
 */
#include <stdio.h>
#include "v1.h"   /* supplies dim_t typedef */

int main(void) {
    dim_t d = get_dimension(3000000000L);
    /* print as both signed-long and unsigned to make truncation visible */
    printf("get_dimension(3000000000) = %ld (0x%lx)\n", (long)d, (unsigned long)d);
    if ((unsigned long)d == 3000000000UL) {
        printf("CORRECT: long is 64-bit, no truncation\n");
    } else {
        printf("TRUNCATED: dim_t is 32-bit, value wrapped to %ld\n", (long)d);
    }
    return 0;
}
