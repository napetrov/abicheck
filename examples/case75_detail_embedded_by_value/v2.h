// case75 v2 — detail::table_impl gains a new field.
//
// Because `table` embeds it by value, sizeof(table) grows. Any consumer
// compiled against v1 will mis-allocate, mis-copy, and mis-pass the
// public `table` type.
#pragma once

#include <cstddef>

namespace mylib {
namespace detail {

struct table_impl {
    std::size_t row_count;
    std::size_t column_count;
    std::size_t layout_kind;   // NEW FIELD — leaks via mylib::table
};

} // namespace detail

class table {
public:
    table();
    std::size_t row_count() const;
    std::size_t column_count() const;
    std::size_t layout_kind() const;
private:
    detail::table_impl impl_;
};

extern "C" table* mylib_make_table();
extern "C" void mylib_free_table(table*);

} // namespace mylib
