// Consumer compiled against v1 references the tagged symbol _Z6get_idB5cxx11v.
// Against v2 that symbol is gone (replaced by _Z6get_idv): undefined symbol
// at load time.
#include "v1.h"

int main() { return get_id() == 42 ? 0 : 1; }
