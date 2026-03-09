#include "lib.h"

static int dispatch_generic(int x) { return x * 2; }

static void *resolve_dispatch(void) { return (void*)dispatch_generic; }

int dispatch(int x) __attribute__((ifunc("resolve_dispatch")));
