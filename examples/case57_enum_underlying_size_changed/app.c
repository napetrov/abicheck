#include <stdio.h>

/* App compiled against v1: Color is int-sized (4 bytes) */
typedef enum { COLOR_RED = 0, COLOR_GREEN = 1, COLOR_BLUE = 2 } Color;
typedef struct { Color color; int alpha; } Pixel;

extern Pixel* pixel_create(Color c, int alpha);
extern void pixel_destroy(Pixel *p);
extern Color pixel_get_color(const Pixel *p);

int main(void) {
    Pixel *p = pixel_create(COLOR_BLUE, 255);
    printf("color = %d\n", pixel_get_color(p));
    /* v1: sizeof(Pixel) = 8,  color at offset 0 (4 bytes), alpha at offset 4 */
    /* v2: sizeof(Pixel) = 16, color at offset 0 (8 bytes), alpha at offset 8 */
    /* → offset mismatch for alpha, size mismatch for allocations */
    pixel_destroy(p);
    return 0;
}
