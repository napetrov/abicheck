class Widget {
public:
    virtual int draw();
    virtual int resize();
};
int Widget::draw()   { return 0; }
int Widget::resize() { return 0; }
