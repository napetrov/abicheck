#include "v1.h"
#include <stdio.h>
#include <string.h>

int main(void) {
    struct Packet pkt;
    memset(&pkt, 0, sizeof(pkt));

    pkt.version      = 1;
    pkt.sequence     = 42;
    pkt.payload_size = 1024;
    pkt.flags        = 0xF;

    printf("sizeof(Packet) = %zu\n", sizeof(pkt));
    printf("version      = %d\n", pkt.version);
    printf("sequence     = %d\n", pkt.sequence);
    printf("payload_size = %d\n", pkt.payload_size);
    printf("flags        = %u\n", pkt.flags);
    printf("packet_send  = %d\n", packet_send(&pkt));

    return 0;
}
