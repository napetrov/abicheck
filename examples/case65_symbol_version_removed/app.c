/* DEMO: app linked against v1 which provides crypto_hash@CRYPTO_1.0.
   When v2 is swapped in (CRYPTO_1.0 version node removed), the dynamic
   linker refuses to load the library — version requirement unsatisfied. */
#include "v1.h"
#include <stdio.h>

int main(void) {
    const char *msg = "hello";
    int h = crypto_hash(msg, 5);
    printf("hash(\"%s\") = %d\n", msg, h);

    int ok = crypto_verify(msg, 5, h);
    printf("verify = %d (expected 1)\n", ok);
    return ok ? 0 : 1;
}
