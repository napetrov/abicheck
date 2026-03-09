#include "old/lib.h"
#include <stdio.h>

int main(void) {
    enum Status s = get_status();
    switch (s) {
        case OK:    printf("OK\n"); break;
        case ERROR: printf("ERROR\n"); break;
        case FOO:   printf("FOO\n"); break;   /* FOO=2, valid in v1 */
        default:    printf("UNKNOWN: %d\n", (int)s); break;
    }
    return 0;
}
