#include "v2.h"

std::size_t utf8_length(const char8_t* text) {
    std::size_t n = 0;
    while (text && text[n]) ++n;
    return n;
}

Utf8View utf8_make(const char8_t* text, std::size_t n) {
    return Utf8View{text, n};
}
