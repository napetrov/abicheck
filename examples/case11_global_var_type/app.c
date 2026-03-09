#include "v1.h"
#include <stdio.h>

int main(void) {
    /* v1 ABI: lib_version is int — app reads only 4 bytes */
    printf("lib_version = %d (as int)\n", lib_version);
    printf("Expected: 5000000000 (shows truncated with v2)\n");
    return 0;
}
