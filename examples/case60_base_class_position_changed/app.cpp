#include <cstdio>

struct Widget;
extern "C" {
    Widget* widget_create(int id);
    void widget_destroy(Widget *w);
    int widget_get_id(Widget *w);
    void widget_draw(Widget *w);
    void widget_click(Widget *w);
}

int main() {
    Widget *w = widget_create(42);
    widget_draw(w);
    widget_click(w);
    printf("id = %d\n", widget_get_id(w));
    widget_destroy(w);
    return 0;
}
