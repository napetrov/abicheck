#include "v1.h"

namespace mylib {

task_arena::task_arena(int concurrency) : concurrency_(concurrency) {}
int task_arena::concurrency() const { return concurrency_; }

extern "C" int mylib_arena_concurrency(int n) {
    task_arena t = n;  // implicit conversion at the boundary (v1)
    return t.concurrency();
}

} // namespace mylib
