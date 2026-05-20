// case108 v2 — `task` removed; replacement is functor-based `task_group`.
#pragma once

#include <functional>

namespace mylib {

// `task` class removed entirely.
// Replacement: a much lighter functor-based interface (mirrors oneTBB's
// `task_group::run(F&&)` shape).
class task_group {
public:
    task_group();
    void run(std::function<void()> f);
    void wait();
};

} // namespace mylib
