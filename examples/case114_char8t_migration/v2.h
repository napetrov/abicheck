#pragma once
#include <cstddef>

// v2: migrated to C++20 `char8_t`. char8_t is a distinct type (mangling code
// Du), so the parameter/field types and the mangled symbols all change.
struct Utf8View {
    const char8_t* data;
    std::size_t size;
};

std::size_t utf8_length(const char8_t* text);
Utf8View utf8_make(const char8_t* text, std::size_t n);
