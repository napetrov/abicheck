#include "v1.h"
#include <stdio.h>

int main(void) {
    /* In v1: sizeof(Variant) = 8  (int tag + union{int,float} = 4+4)
     * In v2: sizeof(Variant) = 16 (int tag + padding + union{int,double} = 4+4+8)
     *
     * The app allocates based on v1's sizeof, but v2's library may
     * expect the larger layout. */
    struct Variant v;
    v.tag = 1;
    v.i = 42;

    printf("sizeof(Variant) = %zu\n", sizeof(struct Variant));
    printf("tag = %d, i = %d\n", v.tag, v.i);

    int result = variant_get_int(&v);
    printf("variant_get_int() = %d\n", result);

    return 0;
}
