#include "v1.hpp"
#include <cstdio>
#include <cstring>

/* Compiled with v1: Buffer<int> is 16 bytes (data_+size_) */
/* At runtime, v2 .so constructor writes 24 bytes (adds capacity_) */
extern template class Buffer<int>;

int main() {
    /* Place a sentinel after the buffer to detect overflow */
    char sentinel_before[4] = "AAA";
    Buffer<int> buf(8);
    char sentinel_after[4] = "BBB";

    std::printf("sentinel_before = %s\n", sentinel_before);
    std::printf("sizeof(Buffer<int>) compiled = %zu\n", sizeof(buf));
    std::printf("sentinel_after  = %s\n", sentinel_after);

    if (strcmp(sentinel_after, "BBB") != 0)
        std::printf("CORRUPTION: sentinel_after overwritten! v2 wrote beyond Buffer\n");

    return 0;
}
