#include "v2.h"

Sensor::Sensor(int id, double initial) : value_(initial), id_(id) {}

Sensor::~Sensor() {}

double Sensor::read() const { return value_; }

void Sensor::calibrate(double offset) { value_ += offset; }

int Sensor::get_id() const { return id_; }

extern "C" Sensor* sensor_create(int id, double initial) {
    return new Sensor(id, initial);
}

extern "C" double sensor_read(const Sensor* s) {
    return s->read();
}

extern "C" void sensor_calibrate(Sensor* s, double offset) {
    s->calibrate(offset);
}
