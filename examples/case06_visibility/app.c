#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    void *h;
    void *sym;

    /* v1 = bad.c (leaky visibility) */
    /* Must be run from the build dir — relative path is intentional for this demo. */
    h = dlopen("./libv1.so", RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen libv1.so: %s\n", dlerror()); return 1; }
    sym = dlsym(h, "internal_helper");
    printf("v1.so (bad): internal_helper %s\n",
           sym ? "EXPORTED (leak!)" : "hidden (unexpected)");
    dlclose(h);

    /* v2 = good.c (hidden by default visibility) */
    h = dlopen("./libv2.so", RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen libv2.so: %s\n", dlerror()); return 1; }
    sym = dlsym(h, "internal_helper");
    printf("v2.so (good): internal_helper %s\n",
           sym ? "EXPORTED (bug!)" : "hidden (correct)");
    dlclose(h);

    return 0;
}
