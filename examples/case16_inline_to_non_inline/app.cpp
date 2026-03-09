#include "v1.hpp"   /* v1: fast_hash is inline — inlined at compile time */
#include <cstdio>

int main() {
    /* app compiled with v1 (inline fast_hash) — call is inlined, no .so dependency */
    std::printf("fast_hash(42) = %d\n", fast_hash(42));
    return 0;
}
