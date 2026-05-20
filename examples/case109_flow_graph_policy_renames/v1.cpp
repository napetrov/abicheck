#include "v1.h"

namespace mylib { namespace flow {

// Force template instantiation so symbols land in the .so.
extern "C" int mylib_flow_run(int x) {
    queue_node node;
    return node.run(x);
}

}} // namespace mylib::flow
