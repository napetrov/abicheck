// v2: reset() loses noexcept — ABI changes in exception-enabled ABIs
#include <stdexcept>

class Buffer {
public:
    Buffer();
    ~Buffer();
    void reset();  // <-- noexcept REMOVED
private:
    int* data_;
    int  size_;
};

Buffer::Buffer() : data_(new int[64]), size_(64) {}
Buffer::~Buffer() { delete[] data_; }

void Buffer::reset() {
    for (int i = 0; i < size_; ++i)
        data_[i] = 0;
    // Now may throw in theory; callers compiled with v1 assume noexcept
}
