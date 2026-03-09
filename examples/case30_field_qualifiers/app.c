/* case30 app: Demonstrate field qualifier change (const, volatile).
 *
 * Compiled against v1.h where SensorConfig fields are plain int.
 * v2.h adds const to sample_rate and volatile to raw_value.
 * Binary layout is unchanged, but the semantic contract is broken:
 * writing to a field that is now const is undefined behavior.
 */
#include "v1.h"
#include <stdio.h>

int main(void) {
    struct SensorConfig cfg;

    /* With v1: all fields are plain int — freely readable and writable */
    cfg.sample_rate = 1000;
    cfg.raw_value = 42;
    cfg.cache_hits = 0;

    printf("Field qualifier change demo (compiled against v1.h):\n\n");

    printf("Initial state:\n");
    printf("  sample_rate = %d\n", cfg.sample_rate);
    printf("  raw_value   = %d\n", cfg.raw_value);
    printf("  cache_hits  = %d\n", cfg.cache_hits);

    /* Call library function */
    int val = sensor_read(&cfg);
    printf("\nsensor_read(&cfg) = %d\n", val);

    /* Modify sample_rate — legal with v1, but UB with v2 (const field) */
    cfg.sample_rate = 2000;
    printf("\nAfter setting sample_rate = 2000:\n");
    printf("  sample_rate = %d\n", cfg.sample_rate);

    /* Modify raw_value — with v2 this field is volatile, so every
     * read/write goes through memory. The binary still works, but
     * the compiler may have optimized reads assuming non-volatile
     * when compiled against v1. */
    cfg.raw_value = 99;
    int r1 = cfg.raw_value;
    int r2 = cfg.raw_value;
    printf("\nraw_value read twice: r1=%d r2=%d (should be equal)\n", r1, r2);
    printf("  With v1: compiler may cache the read (non-volatile)\n");
    printf("  With v2: volatile means every read goes to memory\n");

    val = sensor_read(&cfg);
    printf("\nsensor_read(&cfg) after modifications = %d\n", val);

    printf("\nSummary:\n");
    printf("  - Binary layout: UNCHANGED (no size/offset changes)\n");
    printf("  - sample_rate became const: writing is now UB\n");
    printf("  - raw_value became volatile: compiler must not cache reads\n");
    printf("  - At binary level with v2 lib: app still runs identically\n");
    printf("  - The break is semantic: code that modifies sample_rate\n");
    printf("    violates the v2 API contract (const qualifier)\n");

    return 0;
}
