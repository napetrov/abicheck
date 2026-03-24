#ifndef BUFFER_H
#define BUFFER_H

class Buffer {
public:
    Buffer(int sz);
    virtual ~Buffer();

    /* v2: rvalue ref-qualified — only callable on rvalues.
       Mangled name changes: consume() & -> consume() &&
       e.g. _ZNR6Buffer7consumeEv -> _ZNO6Buffer7consumeEv */
    int consume() &&;

    int size() const;

private:
    int size_;
};

#endif
