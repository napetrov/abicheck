#include <cstdio>

extern "C" {
    void* make_buf();
    void  reset_buf(void* b);
    void  free_buf(void* b);
}

int main() {
    void* b = make_buf();
    printf("Calling reset()...\n");
    reset_buf(b);  /* v1: ok; v2: throws → terminate (noexcept violated) */
    printf("reset() completed OK\n");
    free_buf(b);
    return 0;
}
