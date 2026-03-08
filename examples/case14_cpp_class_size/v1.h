class Buffer {
public:
    int size();
private:
    char data[64];
};
extern "C" Buffer* make_buffer();
