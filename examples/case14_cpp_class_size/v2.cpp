/* data[128] — sizeof(Buffer) doubles, heap allocs undersize the object */
class Buffer {
public:
    int size() { return 128; }
private:
    char data[128];
};
extern "C" Buffer* make_buffer() { return new Buffer(); }
