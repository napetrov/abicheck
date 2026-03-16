/* good.c — same logic, but built with a version script that hides
   dependency symbols. Only core_api is exported. */
int dep_compress(const char *buf, int len);

__attribute__((visibility("default")))
int core_api(const char *data, int size) {
    return dep_compress(data, size);
}
