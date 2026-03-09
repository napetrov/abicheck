#include "lib.h"
#include <cstdio>
#include <cstdlib>

/* Concrete subclass — needed because Processor is abstract in v2 (process()=0),
   so we cannot directly instantiate it. ProcAbortImpl::process() calls abort()
   to simulate the real failure: in a true mixed-version scenario, an old binary
   that directly calls 'new Processor()' (v1 concrete) and then p->process() would
   hit the __cxa_pure_virtual handler in the v2 vtable and abort. */
struct ProcAbortImpl : Processor {
    void process() override {
        fprintf(stderr, "pure virtual method called\n");
        abort();
    }
};

extern "C" Processor* make_proc() { return new ProcAbortImpl(); }
