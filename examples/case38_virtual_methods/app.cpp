#include "v1.hpp"
#include <cstdio>

class MyProcessor : public Processor {
public:
    void execute() override {
        std::printf("MyProcessor::execute() called\n");
    }
};

int main() {
    MyProcessor proc;

    /* Use a base-class reference to force virtual dispatch through
     * the vtable, preventing the compiler from devirtualizing. */
    Processor& ref = proc;

    std::printf("Calling transform(42)...\n");
    ref.transform(42);

    std::printf("Calling validate(10)...\n");
    ref.validate(10);

    std::printf("Calling execute()...\n");
    ref.execute();

    return 0;
}
