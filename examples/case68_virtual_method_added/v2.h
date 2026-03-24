#ifndef SENSOR_H
#define SENSOR_H

/* Virtual method added — class now has a vtable pointer!
   sizeof grows from 16 to 24 bytes (vtable ptr inserted at offset 0).
   All data member offsets shift by 8 bytes (pointer size on x86-64). */
class Sensor {
public:
    Sensor(int id, double initial);
    virtual ~Sensor();             /* NEW: virtual destructor */
    virtual double read() const;   /* was non-virtual, now virtual */
    void   calibrate(double offset);
    int    get_id() const;

private:
    double value_;   /* was offset 0, now offset 8  (shifted by vptr) */
    int    id_;      /* was offset 8, now offset 16 (shifted by vptr) */
};

extern "C" Sensor* sensor_create(int id, double initial);
extern "C" double  sensor_read(const Sensor* s);
extern "C" void    sensor_calibrate(Sensor* s, double offset);

#endif
