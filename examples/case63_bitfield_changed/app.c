/* DEMO: app compiled against v1 layout, but linked to v2 library at runtime.
   v1 priority is at bits 8-15; v2 priority is at bits 10-17.
   The app reads the wrong bits, getting a corrupt priority value. */
#include "v1.h"
#include <stdio.h>

int main(void) {
    RegMap r;
    regmap_init(&r);  /* v2 writes mode=2 into 5-bit field, shifts everything */

    uint32_t pri = regmap_read_priority(&r);
    printf("priority = %u (expected 128)\n", pri);

    /* Also demonstrate the mode field mismatch */
    regmap_set_mode(&r, 3);
    printf("raw word after set_mode(3): 0x%08X\n", *(uint32_t *)&r);

    if (pri != 128) {
        printf("CORRUPTION: priority bits shifted due to bitfield width change!\n");
        return 1;
    }
    return 0;
}
