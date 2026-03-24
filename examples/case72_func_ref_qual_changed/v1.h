#ifndef BUFFER_H
#define BUFFER_H

class Buffer {
public:
    Buffer(int sz);
    virtual ~Buffer();

    /* v1: lvalue ref-qualified — only callable on lvalues */
    int consume() &;

    int size() const;

private:
    int size_;
};

#endif
