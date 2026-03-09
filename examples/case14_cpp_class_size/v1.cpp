class Buffer {
public:
    Buffer() { __builtin_memset(data, 0, sizeof(data)); }
    int size() { return 64; }
private:
    char data[64];
};
extern "C" Buffer* make_buffer() { return new Buffer(); }
