int public_api(int x)      { return x; }
int internal_helper(int x) { return x * 2; }  /* accidentally exported */
int another_impl(int x)    { return x + 3; }  /* accidentally exported */
