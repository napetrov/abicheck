#include "v1.h"
#include <cstdio>

int main() {
    Buffer* b = make_buffer();
    printf("size() = %d (expected 64, v2 returns 128)\n", b->size());
    delete b;
    return 0;
}
