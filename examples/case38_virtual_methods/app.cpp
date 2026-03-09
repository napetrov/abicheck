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

    std::printf("Calling transform(42)...\n");
    proc.transform(42);

    std::printf("Calling validate(10)...\n");
    proc.validate(10);

    std::printf("Calling execute()...\n");
    proc.execute();

    std::printf("Copying processor...\n");
    Processor copy(proc);
    std::printf("Copy created successfully\n");

    return 0;
}
