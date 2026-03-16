/* bad.c — links against dep.a but does NOT hide dependency symbols.
   Result: dep_compress and dep_decompress leak into .dynsym. */
int dep_compress(const char *buf, int len);

int core_api(const char *data, int size) {
    return dep_compress(data, size);
}
