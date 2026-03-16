#include <dlfcn.h>
#include <stdio.h>

int main(void) {
    void *h;
    void *sym;
    const char *names[] = {
        "public_api",
        "_process_buffer_internal",
        "_validate_input_impl",
        "_cache_lookup_detail",
    };
    const char *libs[] = {"./libv1.so", "./libv2.so"};
    int i, j;

    for (j = 0; j < 2; j++) {
        h = dlopen(libs[j], RTLD_NOW);
        if (!h) { fprintf(stderr, "dlopen %s: %s\n", libs[j], dlerror()); continue; }
        printf("\n%s exports:\n", libs[j]);
        for (i = 0; i < 4; i++) {
            sym = dlsym(h, names[i]);
            printf("  %-30s %s\n", names[i],
                   sym ? "EXPORTED" : "hidden");
        }
        dlclose(h);
    }

    return 0;
}
