#include "v1.h"
#include <cstdio>

int main() {
    /* Compiled against v1: consume() is lvalue ref-qualified (&) */
    Buffer buf(42);
    int val = buf.consume();
    std::printf("consume() = %d\n", val);
    std::printf("Expected: 42\n");
    return 0;
}
