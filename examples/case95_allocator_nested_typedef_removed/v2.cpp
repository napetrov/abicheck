#include "v2.h"
#include <cstdlib>

namespace mylib {

int* my_allocator::allocate(std::size_t n) {
    return static_cast<int*>(std::malloc(n * sizeof(int)));
}

void my_allocator::deallocate(int* p, std::size_t) {
    std::free(p);
}

} // namespace mylib
