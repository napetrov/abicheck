// Test: what happens when exception propagates through a noexcept call site?
#include <stdexcept>
#include <cstdio>

void might_throw() {
    throw std::runtime_error("oops");
}

// App sees this (noexcept)
void reset_noexcept() noexcept;
// But at runtime, the .so calls might_throw()

// Actually let's inline-test the mechanism:
void wrapper_noexcept() noexcept {
    might_throw();  // will call terminate because wrapper is noexcept
}

int main() {
    try {
        wrapper_noexcept();
    } catch(...) {
        printf("caught! (would not reach here)\n");
    }
    printf("done\n");
    return 0;
}
