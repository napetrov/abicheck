#include "lib.h"

/* FOO removed in v2 — return the integer value 2 (which was FOO in v1) */
enum Status get_status(void) { return (enum Status)2; }
