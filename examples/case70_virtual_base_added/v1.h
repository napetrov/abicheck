#ifndef WIDGET_H
#define WIDGET_H

class Base {
public:
    int base_val;
    virtual ~Base();
    virtual int value() const;
};

/* v1: non-virtual inheritance */
class Widget : public Base {
public:
    int widget_data;
    Widget(int v, int d);
    int combined() const;
};

#endif
