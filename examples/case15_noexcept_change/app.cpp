// app.cpp — compiled against v1 header (reset() is noexcept)
// When v2.so is loaded, reset() throws → std::terminate via noexcept frame
#include "v1.h"
#include <cstdio>

int main() {
    Buffer* b = make_buf();
    std::printf("Calling reset()...\n");
    // b->reset() is declared noexcept in v1.h — compiler omits landing pads.
    // With v2.so: reset() throws std::runtime_error.
    // The exception escapes the noexcept frame → std::terminate.
    b->reset();
    std::printf("reset() completed OK\n");
    free_buf(b);
    return 0;
}
