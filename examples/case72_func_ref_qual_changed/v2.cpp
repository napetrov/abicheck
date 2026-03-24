#include "v2.h"

Buffer::Buffer(int sz) : size_(sz) {}
Buffer::~Buffer() {}

int Buffer::consume() && {
    int s = size_;
    size_ = 0;
    return s;
}

int Buffer::size() const { return size_; }
