/* added field 'z' — layout change, callers pass wrong-sized structs */
struct Point { int x; int y; int z; };
int get_x(struct Point *p) { return p->x; }
