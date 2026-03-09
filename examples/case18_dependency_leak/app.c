#include "foo_v1.h"
#include <stdio.h>

int main(void) {
    /* Compiled with v1: ThirdPartyHandle = {int x} = 4 bytes */
    ThirdPartyHandle h = {42};
    printf("h.x = %d, sizeof(h) = %zu\n", h.x, sizeof(h));
    process(&h);
    printf("after process: h.x = %d\n", h.x);
    return 0;
}
