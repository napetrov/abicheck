__attribute__((visibility("default"))) int public_api(int x) { return x; }
static int internal_helper(int x) { return x * 2; }  /* hidden */
