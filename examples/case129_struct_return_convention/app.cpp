#include "v1.h"
// Caller that reads the returned aggregate. Compiled against v1's in-register
// return convention; if relinked against v2 (sret) without recompiling, it
// reads the result from the wrong location.
int main() {
    Result r = compute();
    return r.code;
}
