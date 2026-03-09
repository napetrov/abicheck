#include <stdexcept>
#include <cstdio>

// External function declared noexcept (like reset() in v1.h)
// At runtime, it will throw
extern "C" void ext_reset() noexcept;

int main() {
    printf("calling ext_reset()...\n");
    ext_reset();
    printf("returned normally\n");
    return 0;
}
