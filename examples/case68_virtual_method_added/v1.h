#ifndef SENSOR_H
#define SENSOR_H

/* Non-virtual class — no vtable pointer, sizeof = 16 bytes
   (double value + int id, possibly with padding) */
class Sensor {
public:
    Sensor(int id, double initial);
    double read() const;
    void   calibrate(double offset);
    int    get_id() const;

private:
    double value_;   /* offset 0,  8 bytes */
    int    id_;      /* offset 8,  4 bytes */
    /* + 4 bytes padding to align to 8 → sizeof = 16 */
};

extern "C" Sensor* sensor_create(int id, double initial);
extern "C" double  sensor_read(const Sensor* s);
extern "C" void    sensor_calibrate(Sensor* s, double offset);

#endif
