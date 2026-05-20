#include "v2.h"

namespace mylib {

task_group::task_group() {}
void task_group::run(std::function<void()> f) { f(); }
void task_group::wait() {}

} // namespace mylib
