// Demonstrates the source-break behavior of case106.
// The app uses the v1 implicit-conversion shape; it links against either
// version's .so since the mangled name is unchanged.
#include "v1.h"
#include <cstdio>

int main() {
    // This line is the source break: in v2 it no longer compiles because
    // the converting constructor is now `explicit`. Existing binaries that
    // were compiled against v1 keep running against the v2 .so (mangled
    // name unchanged) — only re-compilation surfaces the API break.
    std::printf("concurrency = %d (expect 4)\n", mylib_arena_concurrency(4));
    return 0;
}
