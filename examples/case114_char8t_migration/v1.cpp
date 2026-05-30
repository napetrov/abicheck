#include "v1.h"

std::size_t utf8_length(const char* text) {
    std::size_t n = 0;
    while (text && text[n]) ++n;
    return n;
}

Utf8View utf8_make(const char* text, std::size_t n) {
    return Utf8View{text, n};
}
