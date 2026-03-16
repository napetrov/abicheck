#include <dlfcn.h>
#include <stdio.h>

int main(void) {
    void *h;
    void *sym;

    /* v1 = bad (leaks dependency symbols) */
    h = dlopen("./libv1.so", RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen libv1.so: %s\n", dlerror()); return 1; }

    sym = dlsym(h, "core_api");
    printf("v1.so: core_api     %s\n", sym ? "EXPORTED (correct)" : "missing (bug!)");

    sym = dlsym(h, "dep_compress");
    printf("v1.so: dep_compress %s\n",
           sym ? "EXPORTED (leak!)" : "hidden (correct)");

    sym = dlsym(h, "dep_decompress");
    printf("v1.so: dep_decompress %s\n",
           sym ? "EXPORTED (leak!)" : "hidden (correct)");
    dlclose(h);

    /* v2 = good (dependency symbols hidden via version script) */
    h = dlopen("./libv2.so", RTLD_NOW);
    if (!h) { fprintf(stderr, "dlopen libv2.so: %s\n", dlerror()); return 1; }

    sym = dlsym(h, "core_api");
    printf("v2.so: core_api     %s\n", sym ? "EXPORTED (correct)" : "missing (bug!)");

    sym = dlsym(h, "dep_compress");
    printf("v2.so: dep_compress %s\n",
           sym ? "EXPORTED (bug!)" : "hidden (correct)");
    dlclose(h);

    return 0;
}
