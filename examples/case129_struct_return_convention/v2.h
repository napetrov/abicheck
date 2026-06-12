#ifndef CASE129_H
#define CASE129_H

// v2 gives Result a user-declared destructor. That makes it non-trivial, so the
// ABI now returns it via a hidden caller-provided pointer (sret) instead of in
// registers — the aggregate-return convention flipped for every function that
// returns Result by value, even though the symbol name of compute() is unchanged.
struct Result {
    int code;
    double value;
    ~Result();
};

Result compute();

#endif
