#pragma once
#include <cstddef>

// v1: the UTF-8 API takes plain `const char*` buffers.
struct Utf8View {
    const char* data;
    std::size_t size;
};

std::size_t utf8_length(const char* text);
Utf8View utf8_make(const char* text, std::size_t n);
