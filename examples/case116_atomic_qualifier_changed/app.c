/* Consumer built against v1 treats Buffer::refcount and buffer_count()'s
   return as a plain int. Against v2 they are _Atomic(int), whose size and
   alignment may differ, so the struct layout and return ABI diverge. */
#include "v1.h"

int main(void) {
    Buffer b = {0, 0};
    buffer_retain(&b);
    return buffer_count(&b);
}
