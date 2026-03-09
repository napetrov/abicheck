// app.cpp — compiled against v1 header (reset() is noexcept)
// When v2.so is loaded, reset() throws → std::terminate via noexcept frame
#include <cstdio>
#include <stdexcept>

// Reproduce v1 class declaration (as seen at compile time)
class Buffer {
public:
    Buffer();
    ~Buffer();
    void reset() noexcept;  // <-- compiled with this declaration
private:
    int* data_;
    int  size_;
};

// Factory to create a Buffer whose vtable comes from the loaded .so
extern "C" Buffer* make_buf();
extern "C" void    free_buf(Buffer* b);

int main() {
    Buffer* b = make_buf();
    std::printf("Calling reset()...\n");
    // Call reset() through the v1-declared noexcept method.
    // With v2.so: reset() throws std::runtime_error.
    // Because the declaration here is noexcept, std::terminate fires.
    b->reset();
    std::printf("reset() completed OK\n");
    free_buf(b);
    return 0;
}
