#include "v1.h"
#include <cstring>

extern "C" int parse_config(const char *path) {
    /* Simplified: return 1 if path looks like a config file */
    return path && std::strlen(path) > 0;
}

extern "C" int validate_config(const char *path) {
    return parse_config(path);
}
