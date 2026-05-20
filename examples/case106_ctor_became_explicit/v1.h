// case106 v1 — implicit converting constructor.
//
// Mirrors a common oneTBB-style pattern: a handle type wraps a primitive
// (count, id, version) and accepts an implicit conversion at the call site:
//
//     tbb::task_arena ta = 4;            // implicit conversion from int
//     library.accept(some_int);          // pass-by-value through implicit ctor
//
// The library author later tightens the API by marking the ctor `explicit`.
// No mangled name changes; binaries keep linking. But every consumer source
// that relied on implicit conversion now fails to compile.
#pragma once

namespace mylib {

class task_arena {
public:
    task_arena(int concurrency);  // implicit converting constructor — v1
    int concurrency() const;
private:
    int concurrency_;
};

// Helper that accepts an int via implicit conversion in v1.
extern "C" int mylib_arena_concurrency(int n);

} // namespace mylib
