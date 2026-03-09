#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    void *h;
    void *sym;

    h = dlopen("./libbad.so", RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen libbad.so: %s\n", dlerror()); return 1; }
    sym = dlsym(h, "internal_helper");
    printf("bad.so:  internal_helper %s\n",
           sym ? "EXPORTED (leak!)" : "hidden (ok)");
    dlclose(h);

    h = dlopen("./libgood.so", RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen libgood.so: %s\n", dlerror()); return 1; }
    sym = dlsym(h, "internal_helper");
    printf("good.so: internal_helper %s\n",
           sym ? "EXPORTED (bug!)" : "hidden (correct)");
    dlclose(h);

    return 0;
}
