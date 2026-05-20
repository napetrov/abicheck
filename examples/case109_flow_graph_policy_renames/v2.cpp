#include "v2.h"

namespace mylib { namespace flow {

extern "C" int mylib_flow_run(int x) {
    buffer_node node;
    return node.run(x);
}

}} // namespace mylib::flow
