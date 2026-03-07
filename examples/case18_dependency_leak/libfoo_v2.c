#include "foo_v2.h"
#include <stdio.h>

/* libfoo implementation — source identical, but compiled with new ThirdPartyHandle */
void process(ThirdPartyHandle* h) {
    printf("process: x=%d\n", h->x);
}

int get_value(const ThirdPartyHandle* h) {
    return h->x;
}
