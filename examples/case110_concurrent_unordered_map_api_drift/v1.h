// case110 v1 — concurrent map with a hash-rehash hint as 2nd parameter.
//
// Mirrors a historical oneTBB API where `insert` carried an extra hint
// argument that interacted with the bucket-rehash policy. Modern oneTBB
// dropped the hint, simplifying the signature.
#pragma once
#include <cstddef>

namespace mylib {

class concurrent_unordered_map_int {
public:
    concurrent_unordered_map_int();

    // v1 signature: 2nd argument is a rehash hint.
    void insert(int key, std::size_t rehash_hint);

    int  size() const;

private:
    int size_;
};

} // namespace mylib
