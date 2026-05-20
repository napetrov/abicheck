// case111 v2 — adds a lambda/initializer-style constructor overload.
//
// The new overload `enumerable_thread_specific(std::function<int()>)`
// makes calls like `ets(42)` still resolve to the int-form, but
// brace-init or callable-arg forms become ambiguous:
//
//     mylib::enumerable_thread_specific ets{[]{ return 42; }};  // OK in v2
//     mylib::enumerable_thread_specific ets{value_or_lambda};   // ambiguous
//
// Existing call sites that passed `0` to mean "default-initialized"
// may resolve through the new overload depending on context, silently
// changing the chosen constructor.
#pragma once
#include <functional>

namespace mylib {

class enumerable_thread_specific {
public:
    explicit enumerable_thread_specific(int initial_value);
    // NEW overload — introduces ambiguity at consumer sites.
    explicit enumerable_thread_specific(std::function<int()> init);

    int local() const;

private:
    int value_;
};

} // namespace mylib
