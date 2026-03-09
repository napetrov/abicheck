#include "v2.h"
#include <stdlib.h>
struct Context { int id; int flags; char name[32]; }; /* now internal */
dim_t get_dimension(int axis) { return (dim_t)axis; }
unsigned int create_handle(void) { return 42; }
struct Context *context_create(void) {
    struct Context *c = malloc(sizeof(struct Context));
    return c;
}
void context_destroy(struct Context *ctx) { free(ctx); }
