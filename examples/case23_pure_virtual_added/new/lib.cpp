#include "lib.h"
#include <cstdio>
#include <cstdlib>

/* Concrete subclass — needed because Processor is now abstract in v2.
   When old app calls make_proc() and then p->process() via vtable,
   the slot for process() points to __cxa_pure_virtual in the base
   vtable. Our concrete impl simulates that abort. */
struct ProcAbortImpl : Processor {
    void process() override {
        fprintf(stderr, "pure virtual method called\n");
        abort();
    }
};

extern "C" Processor* make_proc() { return new ProcAbortImpl(); }
