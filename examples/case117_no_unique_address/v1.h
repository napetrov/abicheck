#pragma once
// v1: an empty stateless policy stored as an ordinary member. Because it is
// not [[no_unique_address]], it occupies at least 1 byte and forces padding,
// so Widget is larger than the bare `int value`.
struct EmptyPolicy {};

struct Widget {
    EmptyPolicy policy;   // ordinary member: takes space
    int value;
};

int widget_value(const Widget *w);
