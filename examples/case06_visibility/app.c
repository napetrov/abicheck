#include <dlfcn.h>
#include <stdio.h>

int main(void) {
    void *h;
    int (*fn)(int);

    h = dlopen("./libbad.so", RTLD_NOW);
    fn = (int(*)(int))dlsym(h, "internal_helper");
    printf("bad.so:  internal_helper %s\n",
           fn ? "EXPORTED (leak!)" : "hidden (ok)");
    dlclose(h);

    h = dlopen("./libgood.so", RTLD_NOW);
    fn = (int(*)(int))dlsym(h, "internal_helper");
    printf("good.so: internal_helper %s\n",
           fn ? "EXPORTED (bug!)" : "hidden (correct)");
    dlclose(h);

    return 0;
}
