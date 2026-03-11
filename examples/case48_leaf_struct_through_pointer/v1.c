#include "v1.h"
void  container_init(Container *c, int id, short x, short y) {
    c->id = id; c->position.x = x; c->position.y = y; c->flags = 0;
}
Leaf  container_get_pos(const Container *c) { return c->position; }
int   container_flags(const Container *c)   { return c->flags; }
