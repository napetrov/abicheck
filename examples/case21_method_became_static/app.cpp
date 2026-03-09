#include "old/lib.h"
#include <cstdio>

int main() {
    Widget w;
    w.bar();   /* compiled as instance method call */
    return 0;
}
