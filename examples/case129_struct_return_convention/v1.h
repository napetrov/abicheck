#ifndef CASE129_H
#define CASE129_H

// A small, trivially-copyable aggregate. By the System V x86-64 ABI a struct
// this small and trivial is returned in registers (RAX:RDX), no hidden pointer.
struct Result {
    int code;
    double value;
};

// Public factory: returns Result by value.
Result compute();

#endif
