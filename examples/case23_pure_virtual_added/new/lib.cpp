#include "lib.h"
#include <cstdio>
#include <cstdlib>

/* Simulates __cxa_pure_virtual: what happens when pure virtual is called */
void Processor::process() {
    fprintf(stderr, "pure virtual method called\n");
    abort();
}

extern "C" Processor* make_proc() { return new Processor(); }
