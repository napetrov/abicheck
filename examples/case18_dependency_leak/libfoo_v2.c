#include "foo_v2.h"
#include <stdio.h>

/* libfoo implementation — source identical, but compiled with new ThirdPartyHandle */
void process(ThirdPartyHandle* h) {
    printf("process: x=%d\n", h->x);
    /* v2: ThirdPartyHandle has y field — but caller only allocated 4 bytes! */
    printf("process: y=%d (garbage if caller used v1 sizeof)\n", h->y);
}

int get_value(const ThirdPartyHandle* h) {
    return h->x;
}
