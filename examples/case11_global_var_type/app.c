#include "v1.h"
#include <stdio.h>

int main(void) {
    /* v1 ABI: lib_version is int — app reads only 4 bytes */
    printf("lib_version = %d (as int)\n", lib_version);
    printf("Expected with v2: 705032704 (5000000000 truncated to 32 bits)\n");
    return 0;
}
