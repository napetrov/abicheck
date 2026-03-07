class Buffer {
public:
    int size() { return 64; }
private:
    char data[64];
};
extern "C" Buffer* make_buffer() { return new Buffer(); }
