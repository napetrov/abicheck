#include "v1.h"
#include <cstdio>

extern "C" Widget* make_widget();

int main() {
    Widget* w = make_widget();
    printf("draw()   = %d (expected 10)\n", w->draw());
    printf("resize() = %d (expected 20)\n", w->resize());
    delete w;
    return 0;
}
