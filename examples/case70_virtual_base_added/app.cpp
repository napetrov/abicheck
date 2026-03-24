#include "v1.h"
#include <cstdio>

int main() {
    /* Compiled against v1: Widget layout is {vptr, base_val, widget_data} */
    Widget w(10, 20);
    std::printf("combined() = %d\n", w.combined());
    std::printf("Expected: 30\n");
    return 0;
}
