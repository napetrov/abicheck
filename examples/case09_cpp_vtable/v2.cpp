/* recolor() inserted before resize() — vtable offset of resize() shifts */
class Widget {
public:
    virtual int draw();
    virtual int recolor();
    virtual int resize();
};
int Widget::draw()    { return 0; }
int Widget::recolor() { return 0; }
int Widget::resize()  { return 0; }
