// case95 v2 — modernization removes the legacy nested typedefs.
//
// The class keeps the same exported symbols (`allocate` / `deallocate`),
// so previously-linked binaries still load and run.  But every consumer
// source TU that wrote `typename my_allocator::value_type` (or any other
// removed alias) now fails to compile.
#pragma once
#include <cstddef>

namespace mylib {

class my_allocator {
public:
    int* allocate(std::size_t n);
    void deallocate(int* p, std::size_t n);
};

} // namespace mylib
