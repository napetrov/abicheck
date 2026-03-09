#include "v1.hpp"
#include <cstdio>

struct TestFrame {
    Buffer<int> buf;
    char after[8];
};

int main() {
    printf("sizeof(Buffer<int>) v1 = %zu\n", sizeof(Buffer<int>));
    printf("sizeof(TestFrame)       = %zu\n", sizeof(TestFrame));
    printf("offsetof(after)         = %zu\n", __builtin_offsetof(TestFrame, after));
    printf("Expected: buf=16 (ptr8 + size8), after starts at 16\n");
    return 0;
}
