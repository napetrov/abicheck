// case95 v1 — allocator-style class with the full STL "nested typedef" set.
//
// Mirrors the historical std::allocator<T> shape from C++03/11:
// `value_type`, `pointer`, `reference`, `size_type`, `difference_type`.
// Real-world consumers do `typename Alloc::value_type` and the like, so
// removing any of these is a source break even though the .so symbol
// table is untouched.
#pragma once
#include <cstddef>

namespace mylib {

class my_allocator {
public:
    // Historical nested type aliases that consumers depend on.
    typedef int            value_type;
    typedef int*           pointer;
    typedef int&           reference;
    typedef std::size_t    size_type;
    typedef std::ptrdiff_t difference_type;

    int* allocate(size_type n);
    void deallocate(int* p, size_type n);
};

} // namespace mylib
