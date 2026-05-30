#pragma once
// v2: the same empty policy is now marked [[no_unique_address]], so the
// compiler overlays it with the following member and Widget shrinks. This is a
// real layout change (sizeof and field offsets move) — abicheck catches it via
// the existing size/alignment/offset kinds, no dedicated ChangeKind needed.
struct EmptyPolicy {};

struct Widget {
    [[no_unique_address]] EmptyPolicy policy;  // overlaid: takes no space
    int value;
};

int widget_value(const Widget *w);
