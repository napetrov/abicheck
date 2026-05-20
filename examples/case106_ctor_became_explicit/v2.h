// case106 v2 — same ctor gains `explicit`.
//
// Source code that wrote `task_arena ta = 42;` or relied on implicit
// conversion in argument passing no longer compiles. Mangled name unchanged,
// so previously-compiled binaries still link.
#pragma once

namespace mylib {

class task_arena {
public:
    explicit task_arena(int concurrency);  // NOW EXPLICIT — source break
    int concurrency() const;
private:
    int concurrency_;
};

extern "C" int mylib_arena_concurrency(int n);

} // namespace mylib
