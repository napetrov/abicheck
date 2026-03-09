#include "v2.h"

/* v2 interprets the same memory using changed layout */
int packet_send(struct Packet *pkt) {
    long v = pkt->version;
    int sum = (int)(v & 0xFFFF) + pkt->payload_size + (int)pkt->flags + pkt->priority;
    return sum;
}
