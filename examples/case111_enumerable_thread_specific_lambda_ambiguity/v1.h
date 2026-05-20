// case111 v1 — thread-local storage class with a single init constructor.
//
// Mirrors a historical oneTBB `enumerable_thread_specific<T>` shape:
// constructible with an explicit initial value. Consumers wrote
//
//     mylib::enumerable_thread_specific<int> ets(42);
//
// unambiguously.
#pragma once
#include <functional>

namespace mylib {

class enumerable_thread_specific {
public:
    // Initial-value constructor.
    explicit enumerable_thread_specific(int initial_value);

    int local() const;

private:
    int value_;
};

} // namespace mylib
