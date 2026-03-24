#include "v2.h"

Base::~Base() {}
int Base::value() const { return base_val; }

Widget::Widget(int v, int d) : widget_data(d) { base_val = v; }
int Widget::combined() const { return base_val + widget_data; }
