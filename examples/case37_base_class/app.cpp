#include "v1.hpp"
#include <stdio.h>

int main() {
    /* Scenario 1: ReorderDemo -- base class order swap
     * v1: ReorderDemo : Logger, Serializer
     * v2: ReorderDemo : Serializer, Logger
     *
     * The this-pointer adjustment for each base differs between v1 and v2.
     * Calling a virtual method through the wrong base leads to calling
     * the wrong vtable entry or passing a mis-adjusted this pointer. */
    ReorderDemo rd;
    rd.log_level = 1;
    rd.format = 2;
    rd.process();
    printf("ReorderDemo: log_level=%d, format=%d\n", rd.log_level, rd.format);

    /* Call virtual methods through base pointers */
    Logger *lg = &rd;
    lg->log("hello");
    printf("ReorderDemo::log() called via Logger* OK\n");

    Serializer *sr = &rd;
    sr->serialize("data");
    printf("ReorderDemo::serialize() called via Serializer* OK\n");

    /* Scenario 2: VirtualDemo -- base becomes virtual */
    VirtualDemo vd;
    vd.log_level = 5;
    vd.init();
    printf("VirtualDemo: log_level=%d\n", vd.log_level);

    /* Scenario 3: AddBaseDemo -- new base class added */
    AddBaseDemo ad;
    ad.log_level = 3;
    ad.run();
    printf("AddBaseDemo: log_level=%d\n", ad.log_level);

    return 0;
}
