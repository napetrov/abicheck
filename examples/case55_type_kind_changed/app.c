#include <stdio.h>

/* App compiled against v1 struct layout */
typedef struct { int x; int y; } Data;

extern void data_init(Data *d, int x, int y);
extern int data_sum(const Data *d);

int main(void) {
    Data d;
    data_init(&d, 10, 20);
    printf("sum = %d\n", data_sum(&d));
    /* v1: x=10, y=20, sum=30 */
    /* v2: union — y overlaps x, sum=10 (wrong!) */
    return 0;
}
