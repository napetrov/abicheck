#include <stdio.h>

/* App compiled against v1: aligned(8), sizeof=64, arrays stride by 64 */
typedef struct __attribute__((aligned(8))) {
    char data[56];
    long checksum;
} CacheBlock;

extern void block_init(CacheBlock *b);
extern long block_checksum(const CacheBlock *b);
extern int block_process(CacheBlock *blocks, int count);

int main(void) {
    CacheBlock blocks[4];
    for (int i = 0; i < 4; i++)
        block_init(&blocks[i]);

    printf("sizeof(CacheBlock) = %zu\n", sizeof(CacheBlock));
    printf("alignof(CacheBlock) = %zu\n", _Alignof(CacheBlock));
    printf("ok = %d\n", block_process(blocks, 4));
    /* v1: stride=64 (aligned 8), array is contiguous */
    /* v2: library expects stride=64 (aligned 64), but sizeof may differ
       due to padding — array element access is misaligned */
    return 0;
}
