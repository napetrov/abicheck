/* case48: Leaf struct change propagated through pointer in function param
 *
 * A deeply-nested "leaf" struct changes its layout. The public API passes
 * a pointer to a containing struct that embeds the leaf. Callers compiled
 * against v1 pass a struct with the old leaf size; v2 reads beyond the
 * allocation.
 *
 * BREAKING: TYPE_SIZE_CHANGED on Leaf propagates → Container layout breaks
 * libabigail equivalent: Leaf_Type_Change (indirect path through pointer)
 */
#ifndef CASE48_V1_H
#define CASE48_V1_H

typedef struct Leaf {
    short x;
    short y;
} Leaf;                  /* 4 bytes */

typedef struct Container {
    int  id;
    Leaf position;       /* embedded — offset 4 */
    int  flags;
} Container;

void  container_init(Container *c, int id, short x, short y);
Leaf  container_get_pos(const Container *c);
int   container_flags(const Container *c);

#endif
