#include "v2.h"

namespace mylib {

task_arena::task_arena(int concurrency) : concurrency_(concurrency) {}
int task_arena::concurrency() const { return concurrency_; }

extern "C" int mylib_arena_concurrency(int n) {
    task_arena t(n);  // explicit construction required (v2)
    return t.concurrency();
}

} // namespace mylib
