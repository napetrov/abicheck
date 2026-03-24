#ifndef WIDGET_H
#define WIDGET_H

class Base {
public:
    int base_val;
    virtual ~Base();
    virtual int value() const;
};

/* v2: inheritance changed from non-virtual to virtual.
   This inserts a vbase pointer and changes object layout. */
class Widget : public virtual Base {
public:
    int widget_data;
    Widget(int v, int d);
    int combined() const;
};

#endif
