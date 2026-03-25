#include "old/lib.h"
#include <cstdio>

/* App compiled against v1 header (Widget::bar() instance method).
 * If linked against v2 where bar() is static, the call passes 'this' in %rdi
 * but the static function ignores it — silent UB.
 */
int main() {
    Widget w;
    w.bar();

    /* For demonstration: attempt to call via pointer to member function.
     * In v1, &Widget::bar is a non‑static member function pointer.
     * In v2, &Widget::bar is a static member function pointer (different type).
     * This code compiles against v1, but would fail to compile against v2.
     */
    // void (Widget::*ptr)() = &Widget::bar;   // v1 OK, v2 error

    std::printf("bar() called\n");
    std::printf("If linked against v2 (static), 'this' pointer passed but ignored.\n");
    std::printf("No crash for void no‑arg method, but UB for any method that accesses members.\n");
    return 0;
}