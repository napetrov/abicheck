/* case30: Field qualifier changes (const, volatile)
 *
 * Demonstrates field qualifier scenarios in one C struct:
 * - A field gains const (prevents modification through struct pointer)
 * - A field gains volatile (forces memory reads on every access)
 * - A field's qualifier is removed (cache_hits loses its qualifier)
 *
 * Binary layout: UNCHANGED — these are semantic/source-level changes
 * that affect how consumers may legally interact with the fields.
 *
 * abicheck detects: FIELD_BECAME_CONST, FIELD_BECAME_VOLATILE
 */
#ifndef V1_H
#define V1_H

#ifdef __cplusplus
extern "C" {
#endif

struct SensorConfig {
    int   sample_rate;    /* will become const in v2 */
    int   raw_value;      /* will become volatile in v2 */
    int   cache_hits;     /* plain int in v1, unchanged in v2 */
};

int sensor_read(struct SensorConfig *cfg);

#ifdef __cplusplus
}
#endif
#endif
