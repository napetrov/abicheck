#include "v1.h"
#include <cstdio>
#include <stdexcept>

int main() {
    Buffer* b = make_buf();
    printf("Calling reset() with try/catch...\n");
    try {
        b->reset();  // noexcept in v1.h but v2 throws
        printf("returned normally\n");
    } catch (const std::runtime_error& e) {
        printf("CAUGHT: %s\n", e.what());
    } catch (...) {
        printf("CAUGHT: unknown exception\n");
    }
    free_buf(b);
    return 0;
}
