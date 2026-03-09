/* case30: Field qualifier changes (const, volatile, mutable)
 *
 * Demonstrates three field qualifier scenarios in one type:
 * - A field gains const (prevents modification through struct pointer)
 * - A field gains volatile (forces memory reads on every access)
 * - A mutable field loses mutable (const methods can no longer modify it)
 *
 * Binary layout: UNCHANGED — these are semantic/source-level changes.
 * abicheck detects: FIELD_BECAME_CONST, FIELD_BECAME_VOLATILE, FIELD_LOST_MUTABLE
 */
#ifndef V1_H
#define V1_H

#ifdef __cplusplus
extern "C" {
#endif

struct SensorConfig {
    int   sample_rate;    /* will become const in v2 */
    int   raw_value;      /* will become volatile in v2 */
    int   cache_hits;     /* mutable in v1, non-mutable in v2 */
};

int sensor_read(struct SensorConfig *cfg);

#ifdef __cplusplus
}
#endif
#endif
