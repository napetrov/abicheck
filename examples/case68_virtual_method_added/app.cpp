/* DEMO: app compiled against v1 (non-virtual Sensor, sizeof=16).
   v2 adds a virtual destructor — inserting a vtable pointer at offset 0.
   All field offsets shift by 8 bytes. The app reads value_ from offset 0
   but gets the vtable pointer instead, interpreting it as a double. */
#include "v1.h"
#include <cstdio>
#include <cstring>

extern "C" Sensor* sensor_create(int id, double initial);
extern "C" double  sensor_read(const Sensor* s);
extern "C" void    sensor_calibrate(Sensor* s, double offset);

int main() {
    /* v1 Sensor: [value_(8 bytes)][id_(4 bytes)][pad(4 bytes)] = 16 bytes
       v2 Sensor: [vptr(8 bytes)][value_(8 bytes)][id_(4 bytes)][pad(4)] = 24 bytes */
    Sensor* s = sensor_create(7, 98.6);

    /* With v1: read() accesses value_ at offset 0 → 98.6
       With v2 lib but v1 layout assumption: app may try to read
       field at wrong offset */
    double val = sensor_read(s);
    int id = s->get_id();

    std::printf("sensor id    = %d (expected 7)\n", id);
    std::printf("sensor value = %.1f (expected 98.6)\n", val);

    /* Stack-allocated sensor shows the size mismatch directly */
    std::printf("sizeof(Sensor) compiled = %zu\n", sizeof(Sensor));

    /* If sizeof doesn't match, the stack layout is wrong */
    Sensor local(3, 42.0);
    double local_val = local.read();
    std::printf("local sensor = %.1f (expected 42.0)\n", local_val);

    if (local_val != 42.0) {
        std::printf("CORRUPTION: vtable pointer insertion shifted all fields!\n");
        return 1;
    }

    delete s;
    return 0;
}
