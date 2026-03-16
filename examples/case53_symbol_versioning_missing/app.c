#include <stdio.h>

extern int api_init(void);
extern int api_process(int x);
extern int api_cleanup(void);

int main(void) {
    api_init();
    printf("api_process(21) = %d\n", api_process(21));
    api_cleanup();
    return 0;
}
