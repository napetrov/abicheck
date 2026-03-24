#include "v1.h"
#include <stdio.h>

int main(void) {
    /* Compiled against v1: Packet.data[] is float, packet_sum returns float */
    struct Packet *p = packet_create(1, 4);
    float sum = packet_sum(p);
    printf("packet_sum = %.1f\n", sum);
    printf("Expected: 10.0\n");  /* 1+2+3+4 */
    packet_free(p);
    return 0;
}
