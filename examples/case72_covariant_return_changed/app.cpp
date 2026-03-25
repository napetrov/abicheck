#include "v1.h"
#include <cstdio>

int main() {
    /* Compiled against v1: Circle::clone() returns Circle* */
    Circle c(5);
    Circle *copy = c.clone();
    std::printf("clone radius = %d\n", copy->radius());
    std::printf("Expected: 5\n");
    std::printf("clone area = %d\n", copy->area());
    std::printf("Expected: 75\n");
    delete copy;
    return 0;
}
