#include "v2.h"

/* v2 reads a third argument that v1 callers never pushed */
double transform(double x, double y, double z) {
    return x * 2.0 + y + z;
}
