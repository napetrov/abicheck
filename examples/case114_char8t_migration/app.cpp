// Consumer compiled against v1 references _Z11utf8_lengthPKc (const char*).
// Against v2 the symbol is _Z11utf8_lengthPKDu (const char8_t*): not found.
#include "v1.h"

int main() {
    return (int)utf8_length("hello");
}
