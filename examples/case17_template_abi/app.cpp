#include "v1.hpp"
#include <cstdio>
#include <cstring>

/* Compiled with v1: Buffer<int> is 16 bytes (data_+size_) */
/* At runtime, v2 .so constructor writes 24 bytes (adds capacity_) */
extern template class Buffer<int>;

int main() {
    /* Use a struct to guarantee adjacency of sentinel fields */
    struct {
        Buffer<int> buf;
        char        after[8];
    } frame;
    char before[8] = "BEFORE!";

    std::memcpy(frame.after, "AFTER!!", 8);

    std::printf("sizeof(Buffer<int>) compiled = %zu\n", sizeof(frame.buf));
    std::printf("before init: after  = %.7s\n", frame.after);

    /* Buffer constructor runs here — v2 writes 8 bytes past frame.buf */
    new (&frame.buf) Buffer<int>(8);

    std::printf("after  init: after  = %.7s\n", frame.after);

    if (std::memcmp(frame.after, "AFTER!!", 7) != 0)
        std::printf("CORRUPTION: sentinel overwritten! v2 wrote beyond Buffer\n");

    frame.buf.~Buffer();
    (void)before;
    return 0;
}
