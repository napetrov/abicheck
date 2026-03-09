/* case30 v2: Field qualifier changes applied */
#ifndef V2_H
#define V2_H

#ifdef __cplusplus
extern "C" {
#endif

struct SensorConfig {
    const int    sample_rate;    /* became const: rate is now immutable after init */
    volatile int raw_value;      /* became volatile: hardware-mapped register */
    int          cache_hits;     /* lost mutable: no longer modifiable in const context */
};

int sensor_read(struct SensorConfig *cfg);

#ifdef __cplusplus
}
#endif
#endif
