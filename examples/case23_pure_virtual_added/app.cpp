#include "old/lib.h"
#include <cstdio>

extern "C" Processor* make_proc();

int main() {
    Processor* p = make_proc();
    printf("Calling process()...\n");
    p->process();   /* v1: prints "processing"; v2: aborts */
    printf("Done.\n");
    delete p;
    return 0;
}
