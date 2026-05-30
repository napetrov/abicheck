// Consumer built against v1 assumes the v1 sizeof(Widget) and the v1 offset of
// `value`. Against v2 the [[no_unique_address]] overlay shrinks Widget and
// moves `value`, so the consumer reads the wrong offset.
#include "v1.h"

int main() {
    Widget w{};
    w.value = 7;
    return widget_value(&w);
}
